# check-ars-tlf.py
#
# ReportingEvent（ARS）と、実際に配る図表・ARD が同じものを指しているかを確かめる。
#
# なぜ要るか。ReportingEvent はスキーマに適合していても、図表とは別の経路で作られる。
# 図表は ARD と宣言から描き、ReportingEvent は ARD から組み立てるので、両者が同じ実行の
# 産物である保証はどこにも無い。系統間の突合（compare-ars-json.py）も、両系統の
# ReportingEvent どうしを比べるだけで、図表とは突き合わせていない
# （docs/validation/records/codex-review-2-ledger.md の C2-164）。
#
# 見るもの。
#   1. ReportingEvent の Output が、図表の宣言（tlf-index.csv）と1対1に対応するか
#   2. 結果値が ARD の各行と、解析・操作・群・値まで行単位で対応するか
#   3. 図表のセル台帳が、宣言・ARD の行・ReportingEvent の結果値・配る HTML の実物と
#      対応するか
#   4. 主要評価項目の解析が ReportingEvent にあり、判定の記録と値が一致するか
#   5. 図表ごとの受入基準（display-contract.csv）のうち、CompareTLF.R が読まない項目
#
# 5 の分担。受入基準の行数・行の水準・表示型・根拠の有無・信頼区間の作り方は
# program/r/<試験ID>_CompareTLF.R が値の水準で照合する（層ごとの突合の段階）。ここで見るのは
# その3つで、同じ照合を二度書かない。
#   a. 覆い方。ある表示型が受入基準に1件でも現れたら、宣言（tlf-index.csv）が持つその
#      表示型の表を全件覆っていること。表示型の途中まで入れて残りを黙って落とすと、
#      覆っていない表が「基準に照らして合格」と見分けが付かなくなる
#   b. 分母。`analysis_set`・`data_subset` は例数ではなく集団の識別子で宣言し、その図表の
#      セルが由来する ARD 行の同名の列と集合で突き合わせる。例数の正本は
#      docs/validation/acceptance/analysis-set-condition.csv の n_expected（QC01・QC04 が
#      読む）で、こちらへは写さない。識別子の付け方は docs/decisions/identifier-naming-rule.md
#   c. 信頼区間の宣言の欠落。`ci_method` の空欄は「この図表に信頼区間は無い」という宣言
#      なので、信頼区間のセルを持つ図表が空欄なら食い違いとする。逆（宣言があってセルが
#      無い）は CompareTLF.R が見る。区間セルは `cell_stats` が lcl と ucl の両方を挙げる
#      ことで見分ける（列見出しは系統と言語で変わる）
#
# 使い方
#   python scripts/check-ars-tlf.py [--system sas|r]
#
# 終了コード
#   0 一致 / 1 食い違いあり / 2 材料が無くて確かめられなかった
import sys, os, csv, json, math, re, html, operator, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOL = 1e-8


def read_csv(p, enc='utf-8-sig'):
    with open(p, encoding=enc, newline='') as f:
        return list(csv.DictReader(f))


def ard_key(r):
    """ARD の1行が ReportingEvent のどの結果値にあたるかを表す複合キー。

    群の指し方は事前規定（groupId）とデータ由来（groupValue）で分かれるが、どちらも
    因子と水準の組なので同じ形で持つ。変数の水準は、事前規定の水準集合を渡した集計では
    その集合（ARD の level_set 列）が因子になり、渡していない集計は VARIABLE-LEVEL という
    因子として
    結果を分ける軸になる（C2-141）。並び順に依らないよう並べ替える。
    """
    g = []
    if r.get('group1') and r.get('group1_level'):
        g.append((r['group1'], r['group1_level']))
    if r.get('variable_level'):
        g.append((r.get('level_set') or 'VARIABLE-LEVEL', r['variable_level']))
    return (r.get('analysis_id') or '', r.get('operation_id') or '', tuple(sorted(g)))


def ard_value(r):
    """ARD の値。数値と文字のどちらかが入り、どちらも空の行は推定不能を表す（C2-150）"""
    v = r.get('stat_num') if r.get('stat_type') == 'num' else r.get('stat_char')
    return str(v) if v not in (None, '') else 'NE'


def re_key(aid, res):
    """ReportingEvent の結果値の複合キー。ard_key と同じ形にする"""
    g = [(x.get('groupingId', ''), x.get('groupId') or x.get('groupValue') or '')
         for x in res.get('resultGroups', []) or []]
    return (aid, res.get('operationId') or '', tuple(sorted(g)))


def re_value(res):
    """ReportingEvent の値。rawValue が無い結果は formattedValue が推定不能を表す"""
    v = res.get('rawValue')
    return str(v) if v not in (None, '') else (res.get('formattedValue') or '')


def index_by_key(pairs, label, err):
    """キーと値の組を辞書にする。同じキーが2つあると後の値が前を黙って消すので、
    重複そのものを食い違いとして数える（compare-ars-json.py の C2-157 と同じ扱い）"""
    out, dup = {}, 0
    for k, v in pairs:
        if k in out:
            dup += 1
            if dup <= 3:
                err.append(f'{label}: 結果値のキーが重複 {k}')
        out[k] = v
    if dup:
        err.append(f'{label}: 結果値のキーの重複 {dup} 件')
    return out


def same_value(a, b):
    """値の一致。ReportingEvent は ARD の文字列をそのまま持つので通常は完全一致だが、
    書式が変わっても数値として同じなら一致とみなす"""
    if a == b:
        return True
    try:
        x, y = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(x) and math.isfinite(y)):
        return False
    d = abs(x - y)
    m = max(abs(x), abs(y))
    return (d / m if m > 0 else d) <= TOL


# 配る HTML から表のセルを読む。図表は1ファイル1図表で、見出しの行（th）と本文の行（td）
# からなる。表示型によっては1つの図表が複数の表に分かれる（表 5.4.7.3 は治療相ごとに18表）
# ので、ファイルの中の表を順にたどって本文の行だけを通し番号で数える。台帳の row_seq も
# 表をまたいで通しなので、この数え方と合う。見出しは照合しない（台帳の col_label は系統に
# よって表示文言だったり変数名だったりして、両者は別のものを指す）
_TAG = re.compile(r'<[^>]+>')
_TABLE = re.compile(r'<table[^>]*>(.*?)</table>', re.S)
_TR = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S)
_TD = re.compile(r'<t([hd])[^>]*>(.*?)</t[hd]>', re.S)


def html_text(s):
    """タグを落として実体参照を戻す。改行と行頭の空白は台帳の値に入らないので端を削るが、
    全角空白は行の字下げに使うので削らない"""
    return html.unescape(_TAG.sub('', s)).replace(' ', ' ').strip(' \t\r\n')


def html_rows(path):
    """HTML の本文の行を、ファイルの中の表を順にたどって並べる"""
    with open(path, encoding='utf-8') as f:
        s = f.read()
    out = []
    for t in _TABLE.finditer(s):
        for r in _TR.finditer(t.group(1)):
            cs = _TD.findall(r.group(1))
            if cs and all(k == 'd' for k, _ in cs):
                out.append([html_text(v) for _, v in cs])
    return out


OPS = {'>': operator.gt, '>=': operator.ge, '<': operator.lt, '<=': operator.le}
CMP_RE = re.compile(r'^\s*(\w+)\s*(>=|<=|>|<)\s*(\w+)\s*$')


def pe_rule(pe):
    """受入基準（primary-endpoint.csv）から判定の規則を組む。

    比較の式は「<ARD の統計量> <演算子> <正本の項目>」の形だけを解釈する。読めない式を
    既定の向きで黙って判定すると、正本を変えても判定が変わらない（図表側の prim_values・
    %_pemake も同じ形だけを受ける）。統計量の名前も比較の向きもここへ書かない
    （C3-213。2026-08-31 まで decide() が下限と > を持っていた）。
    戻り値は (統計量, 演算子, 右辺の項目, 閾値) か、組めないときは理由の文字列。
    """
    need = ('analysis_id', 'timepoint', 'threshold',
            'ci_method', 'comparison', 'estimate_operation')
    miss = [k for k in need if not (pe.get(k) or '').strip()]
    if miss:
        return 'PE-CSV: primary-endpoint.csv に ' + '・'.join(miss) + ' が無い'
    m = CMP_RE.match(pe['comparison'])
    if not m:
        return f'PE-CMP: comparison を解釈できない: {pe["comparison"]}'
    stat, op, ref = m.group(1), m.group(2), m.group(3)
    if not (pe.get(ref) or '').strip():
        return f'PE-CMP: comparison の右辺 {ref} が正本の項目に無い: {pe["comparison"]}'
    return (stat, op, ref, pe[ref].strip())


def decide(value, threshold, op):
    """有効性の判定。比較の向きは受入基準の comparison が持ち、ここへは書かない。
    現行の正本では PRT 9.4 の「3年EFS割合の95%信頼区間が閾値である50％を超えること」を
    厳密な > で表すので、ちょうど等しいときは超えていないので NOT MET（C2-131）。
    """
    f = OPS.get(op)
    if f is None:
        raise ValueError(f'比較の演算子を解釈できない: {op}')
    return 'MET' if f(float(value), float(threshold)) else 'NOT MET'


def decide_selftest():
    """判定の境界を試す。実データの下限は閾値から離れているため、この規則が境界で
    どちらへ倒れるかは実データを流すだけでは一度も試されない（C2-131）。正本が名乗り得る
    4つの演算子すべてを境界で試すのは、向きを正本から受け取るようにした以上、規則の
    正しさは演算子の対応表の側にあるためである（C3-213）。
    """
    cases = [(0.60, 0.50, '>', 'MET'),
             (0.50, 0.50, '>', 'NOT MET'),      # ちょうど閾値。超えていない
             (0.5000001, 0.50, '>', 'MET'),
             (0.4999999, 0.50, '>', 'NOT MET'),
             (0.40, 0.50, '>', 'NOT MET'),
             (0.50, 0.50, '>=', 'MET'),
             (0.4999999, 0.50, '>=', 'NOT MET'),
             (0.50, 0.50, '<', 'NOT MET'),
             (0.4999999, 0.50, '<', 'MET'),
             (0.50, 0.50, '<=', 'MET'),
             (0.5000001, 0.50, '<=', 'NOT MET')]
    bad = [(l, t, o, want, decide(l, t, o)) for l, t, o, want in cases
           if decide(l, t, o) != want]
    for l, t, o, want, got in bad:
        print(f'ERROR: 判定の単体試験が落ちた {l} {o} {t}: 期待 {want} / 実際 {got}')
    return len(bad)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--system', choices=['sas', 'r'], default='r')
    a = ap.parse_args()

    n_self = decide_selftest()
    if n_self:
        return 1

    box = boxpath.trial_dir()
    re_p = os.path.join(box, 'datasets', a.system, 'ard', f'reporting-event-{a.system}.json')
    # ARD のファイル名は系統で違う。SAS 系は ard_cards.csv、R 系は ard_cards_r.csv
    ard_p = os.path.join(box, 'datasets', a.system, 'ard',
                         'ard_cards.csv' if a.system == 'sas' else 'ard_cards_r.csv')
    idx_p = os.path.join(REPO, 'docs', 'metadata', 'tlf-index.csv')
    # 受入基準は docs/validation/acceptance/（2026-08-31 に docs/metadata/ から移した）
    pe_p = os.path.join(REPO, 'docs', 'validation', 'acceptance', 'primary-endpoint.csv')
    dc_p = os.path.join(REPO, 'docs', 'validation', 'acceptance', 'display-contract.csv')
    dec_p = os.path.join(box, 'output', 'compare', f'primary_decision_{a.system}.csv')

    for p in (re_p, ard_p, idx_p, pe_p, dc_p):
        if not os.path.isfile(p):
            print(f'ERROR: 材料が無い: {p}')
            return 2

    re_obj = json.load(open(re_p, encoding='utf-8'))
    err = []

    # 1. Output と宣言の対応
    idx_rows = read_csv(idx_p)
    decl = {r['lblid'].strip() for r in idx_rows if (r.get('lblid') or '').strip()}
    outs = {o['id'] for o in re_obj.get('outputs', [])}
    if decl != outs:
        err.append(f'Output と宣言が食い違う: 宣言のみ {sorted(decl - outs)} / '
                   f'Output のみ {sorted(outs - decl)}')
    print(f'図表の宣言 {len(decl)} / Output {len(outs)}')

    # 2. 結果値と ARD の行の対応。総件数だけを数えていた頃は、同じ件数のまま結果の
    #    所属先や値が入れ替わっても通った（C3-015）。ARD の各行から ReportingEvent と
    #    同じ複合キーを組み立て直し、キーの集合・重複・値を行単位で突き合わせる。
    #    組み立ての規則を build-ars-json.py と別に書くのは、生成側の取り違えをそのまま
    #    写して同じ答えを出さないため
    ard = read_csv(ard_p)
    n_res = sum(len(x.get('results', [])) for x in re_obj.get('analyses', []))
    n_ard = len(ard)
    if n_res != n_ard:
        err.append(f'結果値 {n_res:,} 件が ARD の {n_ard:,} 行と合わない')
    from_ard = index_by_key(((ard_key(r), ard_value(r)) for r in ard), 'ARD', err)
    from_re = index_by_key((((re_key(x['id'], res)), re_value(res))
                            for x in re_obj.get('analyses', [])
                            for res in x.get('results', [])), 'ReportingEvent', err)
    only_ard = sorted(set(from_ard) - set(from_re))
    only_re = sorted(set(from_re) - set(from_ard))
    diff = [k for k in set(from_ard) & set(from_re)
            if not same_value(from_ard[k], from_re[k])]
    print(f'結果値 {n_res:,} / ARD {n_ard:,} 行')
    print(f'  行単位の照合 一致 {len(set(from_ard) & set(from_re)) - len(diff):,} / '
          f'ARD のみ {len(only_ard):,} / ReportingEvent のみ {len(only_re):,} / '
          f'値の不一致 {len(diff):,}')
    for k in only_ard[:3]:
        err.append(f'ARD にあって ReportingEvent に無い結果値: {k}')
    for k in only_re[:3]:
        err.append(f'ReportingEvent にあって ARD に無い結果値: {k}')
    for k in sorted(diff)[:3]:
        err.append(f'結果値が ARD と違う {k}: ARD={from_ard[k]} / '
                   f'ReportingEvent={from_re[k]}')
    for n, what in ((len(only_ard), 'ARD にあって ReportingEvent に無い結果値'),
                    (len(only_re), 'ReportingEvent にあって ARD に無い結果値'),
                    (len(diff), '値の食い違う結果値')):
        if n > 3:
            err.append(f'{what} は合わせて {n:,} 件')

    # 3. セル台帳。図表IDの包含だけを見ていた頃は、台帳が無ければ照合を飛ばして成功し、
    #    セルの値も由来も、配る HTML の実物も一度も読んでいなかった（C3-016）。台帳を
    #    必須の材料に格上げし、次の3つを見る。
    #      a. 台帳の図表が、宣言のうち表であるものと一致し、かつ Output にあるか
    #      b. 各セルの由来鍵が ARD のちょうど1行に当たり、その行が ReportingEvent の
    #         結果値として実在するか（セルが名乗る Analysis と Operation の対応）
    #      c. 台帳のセルが、配る HTML の実物と行数・列数・値で一致するか
    #    由来鍵が ARD の行を一意に決めること自体は、6つの台帳すべてについて CompareTLF.R
    #    が見る（C3-106）。ここで件数を確かめるのは、1行に決まらなければセルが指す
    #    Operation を引けないためである
    cells_p = os.path.join(box, 'output', 'compare', f'tlf_cells_{a.system}_ja.csv')
    tlf_dir = os.path.join(box, 'output', 'tlf', f'{a.system}-ja')
    for p in (cells_p, tlf_dir):
        if not os.path.exists(p):
            print(f'ERROR: 材料が無い: {p}')
            return 2
    cells = read_csv(cells_p)
    need = ('lblid', 'row_seq', 'col_seq', 'value', 'analysis_id', 'variable_level',
            'group1_level', 'stat_name', 'cell_stats', 'key_kind')
    lack = [c for c in need if not cells or c not in cells[0]]
    if lack:
        print(f'ERROR: セル台帳に列が無い: {"・".join(lack)}: {cells_p}')
        print('  図表を作り直していない古い台帳。TLF を回し直すこと')
        return 2

    cnt = {}
    LABELS = {'kind': 'key_kind が想定外のセル',
              'none': '由来が ARD に無いセル',
              'many': '由来が ARD の複数行に当たるセル',
              'nore': '由来が ReportingEvent の結果値に無いセル',
              'stat': 'cell_stats の統計量が ARD に無いセル',
              'html': 'HTML と台帳で行数・列数が合わない箇所',
              'value': 'HTML と台帳で値が違うセル'}

    def add(bucket, msg):
        """種類ごとに先頭3件だけを挙げ、残りは末尾で件数にまとめる"""
        cnt[bucket] = cnt.get(bucket, 0) + 1
        if cnt[bucket] <= 3:
            err.append(msg)

    # a. 台帳の図表。台帳は表だけを持ち、図（宣言の display が fig_ で始まるもの）は
    #    持たない。片方向だけを見ていると、宣言済みの表が台帳から落ちても通る
    decl_tab = {r['lblid'].strip() for r in idx_rows
                if (r.get('lblid') or '').strip()
                and not (r.get('display') or '').startswith('fig_')}
    in_cells = {r['lblid'] for r in cells}
    if in_cells != decl_tab:
        err.append(f'セル台帳と宣言の表が食い違う: 台帳のみ {sorted(in_cells - decl_tab)} / '
                   f'宣言のみ {sorted(decl_tab - in_cells)}')
    miss = sorted(in_cells - outs)
    if miss:
        err.append(f'セル台帳にあって Output に無い図表: {miss}')

    # b. セルの由来。台帳の4列は ARD の主キーなので、非空なら ARD のちょうど1行に当たる
    ard_by_key = {}
    for r in ard:
        ard_by_key.setdefault((r.get('analysis_id') or '', r.get('variable_level') or '',
                               r.get('group1_level') or '', r.get('stat_name') or ''),
                              []).append(r)
    KIND = ('', 'repr', 'part')
    for r in cells:
        where = f'{r["lblid"]} 行{r["row_seq"]} 列{r["col_seq"]}'
        if r['key_kind'] not in KIND:
            add('kind', f'key_kind が {r["key_kind"]!r}: {where}')
        k = (r['analysis_id'], r['variable_level'], r['group1_level'], r['stat_name'])
        if any(k):
            hit = ard_by_key.get(k, [])
            if not hit:
                add('none', f'セルの由来が ARD に無い {k}: {where}')
            elif len(hit) > 1:
                add('many', f'セルの由来が ARD の {len(hit)} 行に当たる {k}: {where}')
            elif ard_key(hit[0]) not in from_re:
                add('nore', f'セルの由来が ReportingEvent に無い {ard_key(hit[0])}: {where}')
        # 複数の統計量を1つに並べたセルは、代表の stat_name だけでは由来を数え上げ
        # られない。cell_stats が挙げる統計量がすべて ARD にあることを見る（C3-103）
        for s in (r['cell_stats'] or '').split('+'):
            if s and not ard_by_key.get((r['analysis_id'], r['variable_level'],
                                         r['group1_level'], s)):
                add('stat', f'cell_stats の {s} が ARD に無い: {where}')

    # c. 配る HTML の実物。台帳は図表を描いた側が自分で書き出すものなので、台帳どうしが
    #    一致していても、書き出しと描画が同時にずれていれば気付けない
    grid = {}
    for r in cells:
        grid.setdefault(r['lblid'], {})[(int(r['row_seq']), int(r['col_seq']))] = r
    n_html = 0
    for lbl in sorted(grid):
        p = os.path.join(tlf_dir, lbl + '.html')
        if not os.path.isfile(p):
            add('html', f'配る HTML が無い: {p}')
            continue
        g = grid[lbl]
        ncol = {}
        for i, c in g:
            ncol[i] = max(ncol.get(i, 0), c)
        rows = html_rows(p)
        if len(rows) != len(ncol):
            add('html', f'{lbl}: HTML の本文 {len(rows)} 行が台帳の {len(ncol)} 行と合わない')
            continue
        n_html += 1
        for i, row in enumerate(rows, start=1):
            if len(row) != ncol.get(i, 0):
                add('html', f'{lbl} 行{i}: HTML の {len(row)} 列が台帳の {ncol.get(i, 0)} 列と'
                            '合わない')
                continue
            for j, v in enumerate(row, start=1):
                c = g.get((i, j))
                if c is None or (c['value'] or '') != v:
                    add('value', f'{lbl} 行{i} 列{j}: HTML {v!r} / '
                                 f'台帳 {c and c["value"]!r}')
    print(f'セル台帳 {len(cells):,} セル / 表 {len(grid)} / HTML と照合した表 {n_html}')
    for b, n in sorted(cnt.items()):
        print(f'  {LABELS[b]} {n:,}')
        if n > 3:
            err.append(f'{LABELS[b]} は合わせて {n:,} 件')

    # 4. 主要評価項目。仕様が名指しする解析が ReportingEvent にあり、判定の記録と合うか
    pe = {r['item']: r['value'] for r in read_csv(pe_p)}
    rule = pe_rule(pe)
    aid = pe.get('analysis_id', '')
    an = next((x for x in re_obj.get('analyses', []) if x['id'] == aid), None)
    if isinstance(rule, str):
        err.append(rule)
    elif an is None:
        err.append(f'主要評価項目の解析 {aid} が ReportingEvent に無い')
    else:
        # 判定の記録が無いときに照合を飛ばして成功すると、主要評価項目の下限・上限・判定
        # そのものを見ないまま「ReportingEvent と成果物は対応している」と出る。主要評価項目
        # を宣言した試験では、記録の不在は材料不足として終える
        if not os.path.isfile(dec_p):
            print(f'ERROR: 材料が無い: {dec_p}')
            print('  主要評価項目を宣言した試験では判定の記録が要る。ARD を回し直すこと')
            return 2
        dec_rows = read_csv(dec_p)
        if len(dec_rows) != 1:
            print(f'ERROR: 判定の記録が {len(dec_rows)} 行ある: {dec_p}')
            print('  1行でなければ、どれが主要評価項目の判定かが決まらない。'
                  '先頭行で代用しない')
            return 2
        cstat, cop, cref, thr = rule
        dec = dec_rows[0]
        vals = {}
        for r in an.get('results', []):
            op = (r.get('operationId') or '').rsplit('.', 1)[-1]
            # 群の指し方は2通り。事前規定は groupId、データ由来は groupValue（C2-142）
            g = [x.get('groupId') or x.get('groupValue') or ''
                 for x in r.get('resultGroups', [])]
            if pe['timepoint'] in g or not g:
                vals.setdefault(op, r.get('rawValue'))
        # 記録の estimate 列は正本の estimate_operation の値を、lcl 列は comparison の
        # 左辺の値を持つ（列名は記録の書式であって、統計量の指定ではない）。ucl は判定に
        # 関わらず、正本も項目を持たないので記録の列名のまま照合する
        for key, op in (('estimate', pe['estimate_operation']),
                        ('lcl', cstat), ('ucl', 'ucl')):
            v = vals.get(op)
            if v is None:
                err.append(f'主要評価項目の {op} が ReportingEvent の {aid} に無い')
                continue
            try:
                if abs(float(v) - float(dec[key])) > TOL:
                    err.append(f'主要評価項目の {op} が判定の記録と違う: '
                               f'ReportingEvent={v} / 判定={dec[key]}')
            except (TypeError, ValueError):
                err.append(f'主要評価項目の {op} を数値として比べられない: {v!r} / {dec[key]!r}')
        # 判定そのものを独立に出し直す。両系統が同じ判定を持つことは Compare が見るが、
        # それは実装どうしの一致であって、閾値と比較の向きが仕様どおりかは別である
        # （C2-155）。閾値と比較の向きの正本は docs/validation/acceptance/primary-endpoint.csv
        want = decide(dec['lcl'], thr, cop)
        if want != dec.get('decision'):
            err.append(f'主要評価項目の判定が仕様から出し直した結果と違う: '
                       f'記録={dec.get("decision")} / {cstat} {dec["lcl"]} と {cref} '
                       f'{thr} から {pe["comparison"]} で出し直すと {want}')
        # 記録が名乗る信頼区間の方式。ARD が自分の計算した方式を書き、正本の宣言と
        # 一致していなければ、記録の下限は宣言どおりの量ではない
        if (dec.get('ci_method') or '').strip() != pe['ci_method']:
            err.append(f'主要評価項目の ci_method が正本と違う: '
                       f'記録={dec.get("ci_method")!r} / 正本={pe["ci_method"]}'
                       f'（列が無いなら方式を宣言していない古い記録。ARD を回し直すこと）')
        print(f'主要評価項目 {aid}: 判定 {dec.get("decision")} '
              f'（{pe["estimate_operation"]} {dec.get("estimate")} / '
              f'{cstat} {dec.get("lcl")} / {cref} {thr}・{pe["comparison"]}・'
              f'ci_method {pe["ci_method"]}）')

    # 5. 図表ごとの受入基準。列が欠けたまま回すと、行ごとの照合が1件も走らないまま
    #    合格になるので、列の有無は表の外側で1度だけ見て、欠けていれば材料不足で終える
    #    （CompareTLF.R が ci_method 列について同じ扱いをしている）
    dc = read_csv(dc_p)
    need = ('lblid', 'display', 'n_rows', 'row_levels', 'ci_method',
            'analysis_set', 'data_subset', 'source')
    lack = [c for c in need if not dc or c not in dc[0]]
    if lack:
        print(f'ERROR: 受入基準に列が無い: {"・".join(lack)}: {dc_p}')
        return 2

    by_lbl = {}
    for r in dc:
        lb = (r['lblid'] or '').strip()
        if lb in by_lbl:
            err.append(f'受入基準に {lb} の行が2つある')
        by_lbl[lb] = r

    # a. 覆い方。表示型ごとに、宣言が持つ表と受入基準が持つ表を突き合わせる
    want_by_dp, have_by_dp = {}, {}
    for r in idx_rows:
        lb, dp = (r.get('lblid') or '').strip(), (r.get('display') or '').strip()
        if lb and not dp.startswith('fig_'):
            want_by_dp.setdefault(dp, set()).add(lb)
    for lb, r in by_lbl.items():
        have_by_dp.setdefault((r['display'] or '').strip(), set()).add(lb)
    for dp in sorted(have_by_dp):
        miss = sorted(want_by_dp.get(dp, set()) - have_by_dp[dp])
        odd = sorted(have_by_dp[dp] - want_by_dp.get(dp, set()))
        if miss:
            err.append(f'受入基準が {dp} を途中までしか覆っていない: {miss}')
        if odd:
            err.append(f'受入基準の {dp} に宣言の無い図表がある: {odd}')
    print('受入基準の覆い方: ' + ' / '.join(
        f'{dp} {len(have_by_dp.get(dp, ()))}/{len(want_by_dp[dp])}'
        for dp in sorted(want_by_dp)))

    # b・c. 分母の宣言と、信頼区間の宣言の欠落
    n_pop = 0
    for lb in sorted(by_lbl):
        r = by_lbl[lb]
        g = grid.get(lb)
        if not g:
            err.append(f'{lb}: 受入基準にあるがセル台帳に無い')
            continue
        got = {'analysis_set': set(), 'data_subset': set()}
        n_ci = 0
        for c in g.values():
            k = (c['analysis_id'], c['variable_level'], c['group1_level'], c['stat_name'])
            if any(k):
                hit = ard_by_key.get(k, [])
                # 1行に決まらない鍵は上の b で既に食い違いとして数えている
                if len(hit) == 1:
                    for col in got:
                        got[col].add(hit[0].get(col) or '')
            if {'lcl', 'ucl'} <= set((c['cell_stats'] or '').split('+')):
                n_ci += 1
        for col in ('analysis_set', 'data_subset'):
            exp = {x.strip() for x in (r[col] or '').split('|') if x.strip()}
            act = {x for x in got[col] if x}
            if exp != act:
                err.append(f'{lb}: {col} が宣言と違う（宣言 '
                           f'{"・".join(sorted(exp)) or "なし"} / ARD '
                           f'{"・".join(sorted(act)) or "なし"}）')
            else:
                n_pop += 1
        if n_ci and not (r['ci_method'] or '').strip():
            err.append(f'{lb}: 信頼区間のセルが {n_ci} 個あるのに ci_method が空。'
                       '区間の作り方を宣言しないと、どの式で組まれた区間でも通る')
    print(f'受入基準 {len(by_lbl)} 表 / 集団の照合 {n_pop} 件')

    if err:
        print(f'\n食い違い {len(err)} 件')
        for e in err:
            print(f'  {e}')
        return 1
    print('\nReportingEvent と成果物は対応している')
    return 0


if __name__ == '__main__':
    sys.exit(main())
