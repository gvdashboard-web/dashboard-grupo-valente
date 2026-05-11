#!/usr/bin/env python3
"""Atualiza os dados do dashboard (index.html) sem alterar o layout.

Lê dois CSVs do Sankhya (pivot por vendedor + transacional), recalcula
os agregados e patcha o objeto D{} do index.html no lugar.

Uso:
    python3 atualizar_dados.py \\
        --pivot ~/Downloads/pivot-30.csv \\
        --transacional ~/Downloads/pivot-31.csv

Por padrao usa ~/Documents/gv-dashboard/index.html como alvo.
"""
import argparse, calendar, csv, json, os, re, sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

MANAUS_TZ = timezone(timedelta(hours=-4))

# Reaproveita parsers/categorizacao do gerar_relatorio.py
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))
from gerar_relatorio import (
    parse_pivot, parse_transacional, fmt_brl, SELLER_NAMES
)

# Map vendor key (curto) -> nome cheio como aparece no D{}
VENDOR_FULL_NAMES = {
    'erivan': 'Erivan Lima',
    'lucas':  'Lucas de Mello Valente',
    'roger':  'Róger Silva',
    'jalena': 'Jalena',
    'celio':  'Célio Alex',
}

ABC_CATS = {'Produtos A', 'Produtos B', 'Produtos C'}

MES_ABREV_PT = {1:'jan',2:'fev',3:'mar',4:'abr',5:'mai',6:'jun',
                7:'jul',8:'ago',9:'set',10:'out',11:'nov',12:'dez'}
MES_NOME_PT = {1:'janeiro',2:'fevereiro',3:'marco',4:'abril',5:'maio',
               6:'junho',7:'julho',8:'agosto',9:'setembro',
               10:'outubro',11:'novembro',12:'dezembro'}


def aggregate_csvs(pivot_path, transacional_path):
    """Le os dois CSVs e retorna agregados prontos pro patch."""
    sale_to_vendor = parse_pivot(pivot_path)
    items = parse_transacional(transacional_path, sale_to_vendor)
    return aggregate(items)


def fetch_items_from_ca(ano, mes):
    """Pega items diretamente da API Conta Azul (substitui exportacao manual de CSV)."""
    from ca_client import ContaAzulClient
    from gerar_relatorio import categorizar, marca
    import calendar as cal_mod

    print(f'  Conectando à API Conta Azul...')
    client = ContaAzulClient()

    print(f'  Listando vendedores...')
    vendedores = client.get('/venda/vendedores')

    # Mapeia nomes que estao na CA -> chave curta usada no dashboard
    SELLER_NAMES_LOCAL = {
        'Erivan Lima':            'erivan',
        'Lucas de Mello Valente': 'lucas',
        'Róger Silva':            'roger',
        'Roger de Lima silva':    'roger',
        'Jalena':                 'jalena',
        'Célio Alex':             'celio',
    }
    nome_to_id = {v['nome']: v['id'] for v in vendedores if v['nome'] in SELLER_NAMES_LOCAL}
    print(f'  Vendedores monitorados: {list(nome_to_id.keys())}')

    primeiro = f'{ano:04d}-{mes:02d}-01'
    ultimo  = f'{ano:04d}-{mes:02d}-{cal_mod.monthrange(ano, mes)[1]:02d}'

    items = []
    for nome, vid in nome_to_id.items():
        vendor_key = SELLER_NAMES_LOCAL[nome]
        pagina = 1
        vendas_count = 0
        while True:
            res = client.get('/venda/busca',
                ids_vendedores=[vid],
                data_inicio=primeiro,
                data_fim=ultimo,
                totais='APPROVED',
                pagina=pagina,
                tamanho_pagina=500)
            vendas = res.get('itens', []) if isinstance(res, dict) else []
            if not vendas:
                break
            for venda in vendas:
                sale_id = venda['id']
                sale_numero = venda.get('numero', sale_id[:8])
                try:
                    data = datetime.strptime(venda['data'], '%Y-%m-%d')
                except (ValueError, KeyError):
                    continue
                cliente_nome = venda.get('cliente', {}).get('nome', '?')

                # Busca itens da venda
                try:
                    itens_res = client.get(f'/venda/{sale_id}/itens', tamanho_pagina=200)
                    itens_list = itens_res.get('itens', []) if isinstance(itens_res, dict) else []
                except Exception as e:
                    print(f'    aviso: falha pegando itens da venda {sale_numero}: {e}')
                    continue

                for it in itens_list:
                    qtd = it.get('quantidade', 0) or 0
                    valor_unit = it.get('valor', 0) or 0
                    valor_total = valor_unit * qtd
                    produto = it.get('nome', '')
                    items.append({
                        'sale': str(sale_numero),
                        'data': data,
                        'cliente': cliente_nome,
                        'produto': produto,
                        'qtd': qtd,
                        'valor': valor_total,
                        'vendor': vendor_key,
                        'categoria': categorizar(produto),
                        'marca': marca(produto),
                        'tipo': it.get('tipo', 'PRODUTO'),
                    })
                vendas_count += 1
            # Pagina seguinte?
            if len(vendas) < 500:
                break
            pagina += 1
        print(f'    {nome}: {vendas_count} venda(s)')

    print(f'  Total: {len(items)} itens de {len(set(i["sale"] for i in items))} vendas')
    return items


def aggregate(items):
    """Agrega items em estrutura pronta pro patch do index.html."""
    if not items:
        raise RuntimeError('Sem itens validos pra agregar')

    # Detecta mes/ano dominante a partir das datas
    mes_count = defaultdict(int)
    for it in items:
        mes_count[(it['data'].year, it['data'].month)] += 1
    (ano, mes), _ = max(mes_count.items(), key=lambda kv: kv[1])

    # Filtra so itens do mes detectado (nao mistura)
    items = [it for it in items if it['data'].year == ano and it['data'].month == mes]

    # Agregacoes
    total = 0.0
    pedidos = set(); clientes = set(); itens = 0
    por_dia = defaultdict(float)
    por_v = defaultdict(lambda: {
        'total':0.0,'abc':0.0,'pedidos':set(),'clientes':set(),'itens':0,
        'top_clientes':defaultdict(float),'top_produtos':defaultdict(float),
        'por_dia':defaultdict(float),
    })

    for it in items:
        v = VENDOR_FULL_NAMES.get(it['vendor'])
        if not v:
            continue
        total += it['valor']
        pedidos.add(it['sale']); clientes.add(it['cliente']); itens += int(it['qtd'])
        d = it['data'].strftime('%d/%m')
        por_dia[d] += it['valor']
        pv = por_v[v]
        pv['total'] += it['valor']; pv['pedidos'].add(it['sale'])
        pv['clientes'].add(it['cliente']); pv['itens'] += int(it['qtd'])
        pv['top_clientes'][it['cliente']] += it['valor']
        pv['top_produtos'][it['produto']] += it['valor']
        pv['por_dia'][d] += it['valor']
        if it['categoria'] in ABC_CATS:
            pv['abc'] += it['valor']

    # `dias_passados` = quantos dias TEM DADOS (usado pra projecao e ritmo).
    # `viewing_date` = dia em que o dashboard sera VISTO (usado pra header
    # do dashboard, na narrativa "Ontem"): dia seguinte ao ultimo dia com dados.
    dias_com_dados = sorted({it['data'].day for it in items})
    dias_passados = max(dias_com_dados) if dias_com_dados else 1
    dias_total_mes = calendar.monthrange(ano, mes)[1]
    # Data de exibicao = dia seguinte ao ultimo dia com dados (TV mostra no dia seguinte).
    last_data_date = datetime(ano, mes, dias_passados)
    viewing_date = last_data_date + timedelta(days=1)

    out = {
        'ano': ano,
        'mes': mes,
        'mes_nome': MES_NOME_PT[mes],
        'mes_abrev': MES_ABREV_PT[mes],
        # Timestamp da geracao em horario de Manaus (UTC-4)
        'atualizado_em': datetime.now(MANAUS_TZ).strftime('%d/%m %H:%M'),
        # D.hoje = data de exibicao na TV (dia apos o ultimo registro)
        'hoje': viewing_date.strftime('%Y-%m-%d'),
        # dias_corridos_passados = dias com dados (base da projecao e do ritmo)
        'dias_corridos_passados': dias_passados,
        'dias_corridos_total': dias_total_mes,
        'dias_corridos_restantes': dias_total_mes - dias_passados,
        'total': round(total, 2),
        'pedidos': len(pedidos),
        'clientes': len(clientes),
        'itens': itens,
        'dias_com_venda': len([d for d,v in por_dia.items() if v > 0]),
        'vendas_por_dia': {d: round(v,2) for d,v in sorted(por_dia.items())},
        'vendedores': {},
    }

    for v, d in por_v.items():
        n_ped = len(d['pedidos'])
        out['vendedores'][v] = {
            'fat': round(d['total'], 2),
            'fat_abc': round(d['abc'], 2),
            'pedidos': n_ped,
            'clientes': len(d['clientes']),
            'itens': d['itens'],
            'ticket_medio': round(d['total']/max(n_ped,1), 2),
            'top_clientes': sorted([[k,round(v,2)] for k,v in d['top_clientes'].items()],
                                   key=lambda x:-x[1])[:8],
            'top_produtos': sorted([[k,round(v,2)] for k,v in d['top_produtos'].items()],
                                   key=lambda x:-x[1])[:8],
            'por_dia': {k:round(v,2) for k,v in sorted(d['por_dia'].items())},
        }

    return out


def js_array_of_pairs(pairs):
    """Formata [[str,num],...] como JS literal com aspas duplas."""
    parts = []
    for k, v in pairs:
        parts.append(f'["{k}",{v:g}]')
    return '[' + ','.join(parts) + ']'


def js_obj_dia_valor(d):
    parts = []
    for k, v in d.items():
        parts.append(f'"{k}": {v:g}')
    return '{ ' + ', '.join(parts) + ' }'


# ----- Patch no index.html -----

class Patcher:
    def __init__(self, html_path):
        self.path = Path(html_path)
        self.html = self.path.read_text(encoding='utf-8')
        self.changes = []

    def replace(self, pattern, new_value, label):
        """Substitui um padrão regex. Captura o valor antigo pra log."""
        m = re.search(pattern, self.html)
        if not m:
            self.changes.append((label, '(não encontrado)', '(não aplicado)'))
            return
        old = m.group(0)
        # `new_value` é o texto completo de substituição
        self.html = self.html[:m.start()] + new_value + self.html[m.end():]
        self.changes.append((label, old, new_value))

    def write(self):
        self.path.write_text(self.html, encoding='utf-8')


def patch_global(p, agg):
    p.replace(
        r'hoje:\s*"[^"]+"',
        f'hoje: "{agg["hoje"]}"',
        'hoje'
    )
    p.replace(
        r'atualizado_em:\s*"[^"]*"',
        f'atualizado_em: "{agg["atualizado_em"]}"',
        'atualizado_em'
    )
    p.replace(
        r'dias_corridos_passados:\s*\d+',
        f'dias_corridos_passados: {agg["dias_corridos_passados"]}',
        'dias_corridos_passados'
    )
    p.replace(
        r'dias_corridos_total:\s*\d+',
        f'dias_corridos_total: {agg["dias_corridos_total"]}',
        'dias_corridos_total'
    )
    p.replace(
        r'dias_corridos_restantes:\s*\d+',
        f'dias_corridos_restantes: {agg["dias_corridos_restantes"]}',
        'dias_corridos_restantes'
    )

    # total_maio (ou total_<mes>) - mantém nome existente, troca valor
    p.replace(
        r'total_(maio|junho|julho|agosto|setembro|outubro|novembro|dezembro|janeiro|fevereiro|marco|abril):\s*[\d.]+',
        f'total_maio: {agg["total"]:g}',
        'total_maio'
    )

    # ticket_geral - atualiza só "maio" + var_pct
    m = re.search(r'ticket_geral:\s*\{[^}]+\}', p.html)
    if m:
        old = m.group(0)
        # extrai abril
        abril_m = re.search(r'abril:\s*([\d.]+)', old)
        abril = float(abril_m.group(1)) if abril_m else 0
        ticket = agg['total'] / max(agg['pedidos'], 1)
        var_pct = ((ticket - abril) / abril * 100) if abril else 0
        new = f'ticket_geral: {{ maio: {ticket:.2f}, abril: {abril:g}, var_pct: {var_pct:.1f} }}'
        p.replace(re.escape(old), new, 'ticket_geral')

    # projeção: total * dias_total / dias_passados
    proj = agg['total'] * agg['dias_corridos_total'] / max(agg['dias_corridos_passados'], 1)
    p.replace(
        r'projecao:\s*[\d.]+,?\s*\n',
        f'projecao: {proj:.2f},\n',
        'projecao (global)'
    )

    p.replace(
        r'dias_com_venda:\s*\d+',
        f'dias_com_venda: {agg["dias_com_venda"]}',
        'dias_com_venda'
    )

    # vendas_por_dia
    p.replace(
        r'vendas_por_dia:\s*\{[^}]*\}',
        f'vendas_por_dia: {js_obj_dia_valor(agg["vendas_por_dia"])}',
        'vendas_por_dia'
    )


def _find_section_bounds(html, section_name):
    """Localiza o bloco `section_name: { ... }` no nivel do D{}.
    Retorna (start_brace_idx, end_brace_idx) ou None.
    """
    m = re.search(r'\b' + re.escape(section_name) + r':\s*\{', html)
    if not m:
        return None
    start = m.end() - 1  # idx da '{'
    depth = 0
    for i in range(start, len(html)):
        c = html[i]
        if c == '{': depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return (start, i+1)
    return None


def patch_vendedor(p, nome, vd, meta_global, dias_total=31, dias_passados=1):
    """Atualiza a entrada de um vendedor DENTRO do bloco `vendedores: {...}`.
    Robusto a variacoes no formato do bloco."""
    bounds = _find_section_bounds(p.html, 'vendedores')
    if not bounds:
        p.changes.append((f'vendedor {nome}', '(secao vendedores nao encontrada)', '(skip)'))
        return
    sec_start, sec_end = bounds

    # Match "Vendedor": { ... } com 1 nivel de objeto aninhado (por_dia)
    # (?:[^{}]|\{[^}]*\})* permite chars normais OU um sub-bloco {...} sem nested
    pattern = re.compile(
        r'"' + re.escape(nome) + r'":\s*\{(?:[^{}]|\{[^{}]*\})*\}'
    )
    section = p.html[sec_start:sec_end]
    m = pattern.search(section)
    if not m:
        p.changes.append((f'vendedor {nome}', '(bloco não encontrado)', '(skip)'))
        return

    old_block = m.group(0)

    def find(field, default):
        """Extrai valor de um campo. Suporta arrays [..] e primitivos."""
        # 1. tenta array primeiro (pode ter virgulas internas)
        arr_match = re.search(field + r':\s*(\[[^\]]*\])', old_block)
        if arr_match:
            return arr_match.group(1)
        # 2. valor primitivo (nao para na primeira virgula se for o ultimo)
        val_match = re.search(field + r':\s*([^,\n}]+)', old_block)
        return val_match.group(1).strip() if val_match else default

    ticket_abril = find(r'ticket_abril', '0')
    ticket_trend = find(r'ticket_trend', '[0,0,0]')
    fat_abril = find(r'fat_abril', '0')
    pedidos_abril = find(r'pedidos_abril', '0')

    pct_meta = (vd['fat'] / meta_global * 100) if meta_global else 0
    proj_v = vd['fat'] * dias_total / max(dias_passados, 1)

    por_dia = vd.get('por_dia', {})
    por_dia_js = js_obj_dia_valor(por_dia) if por_dia else '{}'

    new_block = (
        f'"{nome}": {{\n'
        f'      fat_maio: {vd["fat"]:g}, fat_abc: {vd["fat_abc"]:g}, '
        f'pedidos: {vd["pedidos"]}, clientes: {vd["clientes"]}, '
        f'ticket_medio: {vd["ticket_medio"]:g}, ticket_abril: {ticket_abril}, ticket_trend: {ticket_trend},\n'
        f'      pct_meta: {pct_meta:.1f}, projecao: {proj_v:.2f}, '
        f'fat_abril: {fat_abril}, pedidos_abril: {pedidos_abril},\n'
        f'      por_dia: {por_dia_js},\n'
        f'      top_clientes: {js_array_of_pairs(vd["top_clientes"])},\n'
        f'      top_produtos: {js_array_of_pairs(vd["top_produtos"])}\n'
        f'    }}'
    )

    abs_start = sec_start + m.start()
    abs_end   = sec_start + m.end()
    p.html = p.html[:abs_start] + new_block + p.html[abs_end:]
    p.changes.append((f'vendedor {nome}', f'fat={vd["fat"]:.2f} ped={vd["pedidos"]}', 'OK'))


def get_meta_global(html, nome):
    m = re.search(
        r'"' + re.escape(nome) + r'":\s*\{\s*global:\s*([\d.]+|null)',
        html
    )
    if m and m.group(1) != 'null':
        return float(m.group(1))
    return None


def patch_insights(p, nome, vd):
    """Atualiza apenas: novos clientes, clientes_maio, concentracao."""
    # Pega o bloco insights[nome]
    pattern = re.compile(
        r'"' + re.escape(nome) + r'":\s*\{[^{}]*?'
        r'(novos:\s*\[[^\]]*\])[^{}]*?'
        r'(concentracao:\s*\{[^}]*\}|concentracao:\s*null)[^{}]*?'
        r'clientes_maio:\s*(\d+)',
        re.DOTALL
    )
    m = pattern.search(p.html)
    if not m:
        return

    # novos = top_clientes (todos, ate 5)
    novos = vd['top_clientes'][:5]
    novos_js = '[\n        ' + ',\n        '.join(
        f'{{nome:"{k}", valor:{v:g}}}' for k,v in novos
    ) + '\n      ]'

    # concentracao = top cliente com pct = topvalor/total*100
    if vd['top_clientes']:
        topc, topv = vd['top_clientes'][0]
        pct = topv / max(vd['fat'], 1) * 100
        conc_js = f'{{nome:"{topc}", pct:{pct:.1f}}}'
    else:
        conc_js = 'null'

    # Substitui campos
    novos_old = m.group(1)
    p.html = p.html.replace(novos_old, f'novos: {novos_js}')

    conc_old = m.group(2)
    p.html = p.html.replace(conc_old, f'concentracao: {conc_js}')

    # clientes_maio
    p.html = re.sub(
        r'(\b'+re.escape(nome)+r'\b[^}]*?clientes_maio:\s*)\d+',
        lambda mm: mm.group(1) + str(vd['clientes']),
        p.html,
        count=1,
        flags=re.DOTALL
    )

    p.changes.append((f'insights {nome}', f'clientes_maio={vd["clientes"]} novos={len(novos)}', 'OK'))


def patch_historico_projecao(p, agg):
    """Atualiza o ULTIMO ponto de historico_total/historico_vendedor se for projecao.
    Mantem todos os pontos anteriores intactos."""
    ano, mes = agg['ano'], agg['mes']
    mes_str = f"{ano:04d}-{mes:02d}"
    proj_total = agg['total'] * agg['dias_corridos_total'] / max(agg['dias_corridos_passados'], 1)

    # historico_total: troca o objeto que tem mes:"YYYY-MM" e projecao:true
    pattern = re.compile(
        r'(\{mes:"' + mes_str + r'",vlr_bruto:)[\d.]+(,projecao:true\})'
    )
    new_total = pattern.sub(lambda m: f'{m.group(1)}{proj_total:.2f}{m.group(2)}', p.html)
    if new_total != p.html:
        p.html = new_total
        p.changes.append(('historico_total proj', '', f'{proj_total:.2f}'))

    # historico_vendedor[*]: troca o ponto de cada vendedor
    bounds = _find_section_bounds(p.html, 'historico_vendedor')
    if not bounds:
        return
    sec_start, sec_end = bounds

    for nome, vd in agg['vendedores'].items():
        proj_v = vd['fat'] * agg['dias_corridos_total'] / max(agg['dias_corridos_passados'], 1)
        # Encontra o array do vendedor: "Nome": [ ... ]
        vp = re.compile(
            r'("' + re.escape(nome) + r'":\s*\[[^\]]*\{mes:"' + mes_str + r'",vlr_bruto:)[\d.]+(,projecao:true\})',
            re.DOTALL
        )
        section = p.html[sec_start:sec_end]
        m = vp.search(section)
        if m:
            new_section = section[:m.start(0)] + m.group(1) + f'{proj_v:.2f}' + m.group(2) + section[m.end(0):]
            p.html = p.html[:sec_start] + new_section + p.html[sec_end:]
            sec_end = sec_start + len(new_section)  # ajusta depois da substituicao
            p.changes.append((f'historico {nome} proj', '', f'{proj_v:.2f}'))

    # Vendedores SEM dados (zero)
    for nome_full in VENDOR_FULL_NAMES.values():
        if nome_full in agg['vendedores']:
            continue
        vp = re.compile(
            r'("' + re.escape(nome_full) + r'":\s*\[[^\]]*\{mes:"' + mes_str + r'",vlr_bruto:)[\d.]+(,projecao:true\})',
            re.DOTALL
        )
        section = p.html[sec_start:sec_end]
        m = vp.search(section)
        if m:
            new_section = section[:m.start(0)] + m.group(1) + '0' + m.group(2) + section[m.end(0):]
            p.html = p.html[:sec_start] + new_section + p.html[sec_end:]
            sec_end = sec_start + len(new_section)


# ----- Main -----

def main():
    ap = argparse.ArgumentParser(
        description='Atualiza index.html. Pode usar CSVs (Sankhya) OU API Conta Azul.'
    )
    ap.add_argument('--pivot', help='CSV pivot por vendedor (modo CSV)')
    ap.add_argument('--transacional', help='CSV transacional (modo CSV)')
    ap.add_argument('--ca-fetch', action='store_true',
                    help='Puxar dados da API Conta Azul (em vez de CSVs)')
    ap.add_argument('--mes', type=int, default=None,
                    help='Mes a buscar (1-12) — usado com --ca-fetch (default: mes atual)')
    ap.add_argument('--ano', type=int, default=None,
                    help='Ano a buscar — usado com --ca-fetch (default: ano atual)')
    ap.add_argument('--target', default=None,
                    help='Caminho do index.html (default: ~/Documents/gv-dashboard/index.html)')
    args = ap.parse_args()

    target = Path(args.target) if args.target else Path.home() / 'Documents' / 'gv-dashboard' / 'index.html'
    if not target.exists():
        print(f'Alvo nao existe: {target}', file=sys.stderr); sys.exit(1)

    if args.ca_fetch:
        now = datetime.now()
        ano = args.ano or now.year
        mes = args.mes or now.month
        print(f'Modo Conta Azul — buscando vendas de {MES_NOME_PT[mes]}/{ano}...')
        items = fetch_items_from_ca(ano, mes)
        agg = aggregate(items)
    else:
        if not args.pivot or not args.transacional:
            print('ERRO: precisa de --pivot + --transacional OU --ca-fetch', file=sys.stderr)
            sys.exit(1)
        print(f'Lendo CSVs...')
        agg = aggregate_csvs(args.pivot, args.transacional)
    print(f'  Mes detectado: {agg["mes_nome"]}/{agg["ano"]}')
    print(f'  Total: {fmt_brl(agg["total"])} | Pedidos: {agg["pedidos"]} | Clientes: {agg["clientes"]}')
    print(f'  Vendedores com dados: {", ".join(agg["vendedores"].keys())}')
    print()

    p = Patcher(target)

    # Aviso: dashboard tem campos hardcoded (_maio, clientes_maio, etc.).
    # Se o mes detectado nao for o "mes ativo" do dashboard, alguns
    # campos vao precisar ser renomeados manualmente no index.html.
    if not re.search(r'total_(' + agg['mes_nome'].replace('marco','marco|março') + r'):', p.html):
        print(f'AVISO: o dashboard parece estar configurado para outro mes que nao "{agg["mes_nome"]}".')
        print(f'       Os campos *_maio, clientes_maio etc. podem ficar inconsistentes.')
        print()

    # captura "antes" pra um diff comparativo no fim
    before_total = re.search(r'total_\w+:\s*([\d.]+)', p.html)
    before_total = float(before_total.group(1)) if before_total else 0

    # 1) globais
    patch_global(p, agg)

    # 2) por vendedor (patch_vendedor ja calcula+escreve a projecao individual)
    for nome, vd in agg['vendedores'].items():
        meta = get_meta_global(p.html, nome)
        patch_vendedor(p, nome, vd, meta, agg['dias_corridos_total'], agg['dias_corridos_passados'])
        patch_insights(p, nome, vd)

    # 3) zera vendedores SEM dados (mantem historico mas zera fat_maio/pedidos)
    for nome_full in VENDOR_FULL_NAMES.values():
        if nome_full in agg['vendedores']:
            continue
        # vendedor nao teve venda -> zera
        zero = {'fat':0,'fat_abc':0,'pedidos':0,'clientes':0,'itens':0,'ticket_medio':0,
                'top_clientes':[],'top_produtos':[]}
        patch_vendedor(p, nome_full, zero, get_meta_global(p.html, nome_full), agg['dias_corridos_total'], agg['dias_corridos_passados'])

    # 4) atualiza ponto de projecao no historico
    patch_historico_projecao(p, agg)

    p.write()

    # relatorio
    print('=== Mudancas aplicadas ===')
    print(f'  Total dashboard: {fmt_brl(before_total)} -> {fmt_brl(agg["total"])}')
    print(f'  Vendas/dia: {agg["vendas_por_dia"]}')
    print()
    for v, d in agg['vendedores'].items():
        print(f'  {v:30s}: {fmt_brl(d["fat"]):>16} | {d["pedidos"]:>3} pedidos | {d["clientes"]:>3} clientes')
    print()
    print(f'OK index.html atualizado: {target}')
    print(f'Pra publicar: bash ~/Documents/gv-dashboard/upload.sh "Atualizacao {agg["mes_nome"]} {agg["dias_corridos_passados"]:02d}/{agg["mes"]:02d}"')


if __name__ == '__main__':
    main()
