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
        'vendas_acumuladas':{},  # {sale_id: {data, cliente, valor}}
    })
    # Sales aggregation (pra calcular venda_destaque)
    sales_agg = defaultdict(lambda: {
        'data': None, 'cliente': '', 'vendor': '', 'valor': 0.0,
        'top_produto': defaultdict(float),
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
        # Acumula vendas individuais por sale_id
        sale_id = it['sale']
        if sale_id not in pv['vendas_acumuladas']:
            pv['vendas_acumuladas'][sale_id] = {
                'data': it['data'], 'cliente': it['cliente'], 'valor': 0
            }
        pv['vendas_acumuladas'][sale_id]['valor'] += it['valor']
        # Acumula tambem no sales_agg geral (pra venda_destaque)
        sa = sales_agg[sale_id]
        sa['data'] = it['data']
        sa['cliente'] = it['cliente']
        sa['vendor'] = v
        sa['valor'] += it['valor']
        sa['top_produto'][it['produto']] += it['valor']
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

    # ----- Venda destaque: maior venda do ultimo dia com vendas -----
    venda_destaque = None
    if sales_agg:
        last_day = max(s['data'].date() for s in sales_agg.values())
        sales_last = [s for s in sales_agg.values() if s['data'].date() == last_day]
        if sales_last:
            top_sale = max(sales_last, key=lambda s: s['valor'])
            top_prod = max(top_sale['top_produto'].items(), key=lambda kv: kv[1])[0] if top_sale['top_produto'] else ''
            parts = top_prod.split(' - ')
            prod_nome = parts[0].strip() if parts else top_prod
            prod_marca = parts[-1].strip() if len(parts) > 1 else ''
            venda_destaque = {
                'data': top_sale['data'].strftime('%d/%m'),
                'cliente': top_sale['cliente'],
                'valor': round(top_sale['valor'], 2),
                'vendedor': top_sale['vendor'],
                'produto_top': prod_nome,
                'produto_top_marca': prod_marca,
            }

    out = {
        'ano': ano,
        'mes': mes,
        'mes_nome': MES_NOME_PT[mes],
        'mes_abrev': MES_ABREV_PT[mes],
        'venda_destaque': venda_destaque,
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
        # Ultimas 5 vendas ordenadas por data desc
        vendas_ord = sorted(d['vendas_acumuladas'].values(),
                            key=lambda x: x['data'], reverse=True)[:5]
        ultimas = [
            {
                'data': u['data'].strftime('%d/%m'),
                'cliente': u['cliente'],
                'valor': round(u['valor'], 2)
            }
            for u in vendas_ord
        ]
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
            'ultimas_vendas': ultimas,
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


def parse_historico_total_anterior(html, ano, mes):
    """Le D.historico_total e retorna (valor_mes_anterior, nome_mes_anterior)."""
    if mes == 1:
        ano_ant, mes_ant = ano - 1, 12
    else:
        ano_ant, mes_ant = ano, mes - 1
    mes_str = f'{ano_ant:04d}-{mes_ant:02d}'
    m = re.search(r'\{mes:"' + mes_str + r'",vlr_bruto:([\d.]+)', html)
    val = float(m.group(1)) if m else 0.0
    return val, MES_NOME_PT[mes_ant].capitalize()


def parse_historico_max_per_vendor(html, ano_atual, mes_atual):
    """Le D.historico_vendedor[*] e retorna {nome: max_vlr_bruto} excluindo o mes atual (projecao)."""
    out = {}
    mes_atual_str = f'{ano_atual:04d}-{mes_atual:02d}'
    for nome in VENDOR_FULL_NAMES.values():
        pattern = re.compile(r'"' + re.escape(nome) + r'":\s*\[(.*?)\]', re.DOTALL)
        m = pattern.search(html)
        if not m:
            out[nome] = 0
            continue
        body = m.group(1)
        # Cada entrada: {mes:"YYYY-MM",vlr_bruto:N[,projecao:true]}
        entries = re.findall(r'\{mes:"([^"]+)",vlr_bruto:([\d.]+)(?:,projecao:(true|false))?\}', body)
        # Exclui o mes atual (proj) — usa so meses fechados
        valid = [float(v) for (m_str, v, proj) in entries
                 if m_str != mes_atual_str and proj != 'true']
        out[nome] = max(valid) if valid else 0
    return out


def _compute_badges(vd, meta_global, dias_passados, dias_total, historic_max):
    """Calcula lista de badges pra um vendedor.
    Formato: ['recorde'] | ['streak', N] | ['acima'] | ['abaixo']
    Maximo de 4 mas a UI corta em 2 com prioridade RECORDE > STREAK > ACIMA/ABAIXO.
    """
    badges = []
    fat = vd.get('fat', 0) or 0

    # 1. RECORDE: total do mes atual maior que o maior mes fechado historico
    if historic_max > 0 and fat > historic_max:
        badges.append(['recorde'])

    # 2. STREAK: dias consecutivos com venda terminando no ultimo dia com dados.
    # `por_dia` tem chaves DD/MM — como aggregate filtra so o mes atual,
    # podemos comparar so o DIA (DD).
    por_dia = vd.get('por_dia', {}) or {}
    dias_com_venda = sorted(
        {int(d.split('/')[0]) for d, v in por_dia.items() if v > 0}
    )
    streak = 0
    if dias_com_venda:
        streak = 1
        for i in range(len(dias_com_venda) - 1, 0, -1):
            if dias_com_venda[i] - dias_com_venda[i-1] == 1:
                streak += 1
            else:
                break
    if streak >= 5:
        badges.append(['streak', streak])

    # 3. ACIMA / ABAIXO: ritmo proporcional vs meta
    if meta_global and dias_passados > 0 and dias_total > 0:
        ritmo_esperado = meta_global / dias_total * dias_passados
        if ritmo_esperado > 0:
            ratio = fat / ritmo_esperado
            if ratio > 1.2:
                badges.append(['acima'])
            elif ratio < 0.6:
                badges.append(['abaixo'])

    return badges


def badges_to_js(badges):
    """Converte lista de badges em literal JS compacto."""
    parts = []
    for b in badges:
        if isinstance(b, list):
            inner = ','.join(f'"{x}"' if isinstance(x, str) else str(x) for x in b)
            parts.append(f'[{inner}]')
        else:
            parts.append(f'"{b}"')
    return '[' + ','.join(parts) + ']'


def patch_vendedor(p, nome, vd, meta_global, dias_total=31, dias_passados=1, historic_max=0):
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

    # Ultimas vendas — array de objetos {data, cliente, valor}
    ultimas = vd.get('ultimas_vendas', [])
    def esc(s):
        return s.replace('\\', '\\\\').replace('"', '\\"')
    ult_parts = []
    for u in ultimas:
        ult_parts.append(
            f'{{data:"{u["data"]}",cliente:"{esc(u["cliente"])}",valor:{u["valor"]:g}}}'
        )
    ultimas_js = '[' + ','.join(ult_parts) + ']'

    # Badges
    badges = _compute_badges(vd, meta_global, dias_passados, dias_total, historic_max)
    badges_js = badges_to_js(badges)

    new_block = (
        f'"{nome}": {{\n'
        f'      fat_maio: {vd["fat"]:g}, fat_abc: {vd["fat_abc"]:g}, '
        f'pedidos: {vd["pedidos"]}, clientes: {vd["clientes"]}, '
        f'ticket_medio: {vd["ticket_medio"]:g}, ticket_abril: {ticket_abril}, ticket_trend: {ticket_trend},\n'
        f'      pct_meta: {pct_meta:.1f}, projecao: {proj_v:.2f}, '
        f'fat_abril: {fat_abril}, pedidos_abril: {pedidos_abril}, badges: {badges_js},\n'
        f'      por_dia: {por_dia_js},\n'
        f'      ultimas_vendas: {ultimas_js},\n'
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
    """Atualiza apenas: novos clientes, clientes_maio, concentracao DENTRO de insights.

    Bug antigo: o regex global usava [^{}]*? que falha porque queda/silencio
    contem sub-objetos {nome:...}. Aqui usamos brace-counting pra delimitar
    o bloco do vendedor e fazer substituicoes locais.
    """
    bounds = _find_section_bounds(p.html, 'insights')
    if not bounds:
        return
    sec_start, sec_end = bounds
    section = p.html[sec_start:sec_end]

    # Acha o "Nome": { dentro da secao com brace counting
    km = re.search(r'"' + re.escape(nome) + r'":\s*\{', section)
    if not km:
        p.changes.append((f'insights {nome}', '(bloco não encontrado)', '(skip)'))
        return
    blk_start = km.end() - 1  # '{'
    depth = 0
    blk_end = None
    for i in range(blk_start, len(section)):
        c = section[i]
        if c == '{': depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                blk_end = i + 1
                break
    if blk_end is None:
        return
    block = section[blk_start:blk_end]

    def esc(s):
        return (s or '').replace('\\', '\\\\').replace('"', '\\"')

    # novos = top_clientes (ate 5)
    novos = vd['top_clientes'][:5]
    novos_js = '[\n        ' + ',\n        '.join(
        f'{{nome:"{esc(k)}", valor:{v:g}}}' for k,v in novos
    ) + '\n      ]'
    new_block = re.sub(r'novos:\s*\[[^\]]*\]', 'novos: ' + novos_js.replace('\\','\\\\'),
                       block, count=1, flags=re.DOTALL)
    # Workaround: re.sub interpreta \1 etc em replacement string; usamos lambda
    new_block = re.sub(r'novos:\s*\[[^\]]*\]', lambda _: f'novos: {novos_js}',
                       block, count=1, flags=re.DOTALL)

    # concentracao
    if vd['top_clientes']:
        topc, topv = vd['top_clientes'][0]
        pct = topv / max(vd['fat'], 1) * 100
        conc_js = f'{{nome:"{esc(topc)}", pct:{pct:.1f}}}'
    else:
        conc_js = 'null'
    new_block = re.sub(r'concentracao:\s*(\{[^}]*\}|null)',
                       lambda _: f'concentracao: {conc_js}',
                       new_block, count=1)

    # clientes_maio
    new_block = re.sub(r'clientes_maio:\s*\d+',
                       f'clientes_maio: {vd["clientes"]}',
                       new_block, count=1)

    # Aplica no html
    section_new = section[:blk_start] + new_block + section[blk_end:]
    p.html = p.html[:sec_start] + section_new + p.html[sec_end:]
    p.changes.append((f'insights {nome}',
                      f'clientes={vd["clientes"]} novos={len(novos)} pct={pct if vd["top_clientes"] else 0:.1f}',
                      'OK'))


def patch_extras(p, agg, mes_ant_val, mes_ant_nome):
    """Patcha os campos novos: mes_anterior_total, mes_anterior_nome, venda_destaque,
    mes_nome_atual, ano_atual."""
    # mes_anterior_total
    if re.search(r'mes_anterior_total:\s*[\d.]+', p.html):
        p.replace(
            r'mes_anterior_total:\s*[\d.]+',
            f'mes_anterior_total: {mes_ant_val:.2f}',
            'mes_anterior_total'
        )
    else:
        # primeira execucao — injeta depois de total_maio
        p.html = re.sub(
            r'(total_(?:maio|junho|julho|agosto|setembro|outubro|novembro|dezembro|janeiro|fevereiro|marco|abril):\s*[\d.]+,)',
            lambda m: m.group(1) + f'\n  mes_anterior_total: {mes_ant_val:.2f},\n  mes_anterior_nome: "{mes_ant_nome}",',
            p.html,
            count=1
        )
        p.changes.append(('mes_anterior_total (inserido)', '', f'{mes_ant_val:.2f}'))

    if re.search(r'mes_anterior_nome:\s*"[^"]*"', p.html):
        p.replace(
            r'mes_anterior_nome:\s*"[^"]*"',
            f'mes_anterior_nome: "{mes_ant_nome}"',
            'mes_anterior_nome'
        )

    # mes_nome_atual + ano_atual (campos novos pro hero)
    mes_atual_capit = MES_NOME_PT[agg['mes']].capitalize().replace('Marco','Março')
    if re.search(r'mes_nome_atual:\s*"[^"]*"', p.html):
        p.replace(r'mes_nome_atual:\s*"[^"]*"', f'mes_nome_atual: "{mes_atual_capit}"', 'mes_nome_atual')
    else:
        p.html = re.sub(
            r'(mes_anterior_nome:\s*"[^"]*",)',
            lambda m: m.group(1) + f'\n  mes_nome_atual: "{mes_atual_capit}",\n  ano_atual: {agg["ano"]},',
            p.html,
            count=1
        )
        p.changes.append(('mes_nome_atual (inserido)', '', mes_atual_capit))
    if re.search(r'ano_atual:\s*\d+', p.html):
        p.replace(r'ano_atual:\s*\d+', f'ano_atual: {agg["ano"]}', 'ano_atual')

    # venda_destaque (objeto ou null)
    vd = agg.get('venda_destaque')
    def esc(s):
        return (s or '').replace('\\', '\\\\').replace('"', '\\"')
    if vd:
        vd_js = (
            f'{{ data: "{vd["data"]}", cliente: "{esc(vd["cliente"])}", '
            f'valor: {vd["valor"]:g}, vendedor: "{esc(vd["vendedor"])}", '
            f'produto_top: "{esc(vd["produto_top"])}", '
            f'produto_top_marca: "{esc(vd["produto_top_marca"])}" }}'
        )
    else:
        vd_js = 'null'
    # tenta substituir; se nao existir o campo no HTML, inserir
    if re.search(r'venda_destaque:\s*(\{[^}]*\}|null)', p.html):
        p.replace(
            r'venda_destaque:\s*(\{[^}]*\}|null)',
            f'venda_destaque: {vd_js}',
            'venda_destaque'
        )
    else:
        # injeta depois de projecao:
        p.html = re.sub(
            r'(projecao:\s*[\d.]+,?\n)',
            lambda m: m.group(1) + f'  venda_destaque: {vd_js},\n',
            p.html,
            count=1
        )
        p.changes.append(('venda_destaque (inserido)', '', vd_js[:60] + '...'))


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

    # ----- Le contexto historico do HTML antes de patchar -----
    mes_ant_val, mes_ant_nome = parse_historico_total_anterior(p.html, agg['ano'], agg['mes'])
    historic_max = parse_historico_max_per_vendor(p.html, agg['ano'], agg['mes'])
    print(f'  Mes anterior ({mes_ant_nome}): {fmt_brl(mes_ant_val)}')
    print(f'  Historic max por vendedor: {historic_max}')
    print()

    # 1) globais
    patch_global(p, agg)
    patch_extras(p, agg, mes_ant_val, mes_ant_nome)

    # 2) por vendedor (patch_vendedor ja calcula+escreve a projecao individual)
    for nome, vd in agg['vendedores'].items():
        meta = get_meta_global(p.html, nome)
        hmax = historic_max.get(nome, 0)
        patch_vendedor(p, nome, vd, meta, agg['dias_corridos_total'], agg['dias_corridos_passados'], hmax)
        patch_insights(p, nome, vd)

    # 3) zera vendedores SEM dados (mantem historico mas zera fat_maio/pedidos)
    for nome_full in VENDOR_FULL_NAMES.values():
        if nome_full in agg['vendedores']:
            continue
        # vendedor nao teve venda -> zera
        zero = {'fat':0,'fat_abc':0,'pedidos':0,'clientes':0,'itens':0,'ticket_medio':0,
                'top_clientes':[],'top_produtos':[]}
        patch_vendedor(p, nome_full, zero, get_meta_global(p.html, nome_full),
                       agg['dias_corridos_total'], agg['dias_corridos_passados'], 0)

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
