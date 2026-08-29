# check-tlf-index.py
#
# docs/metadata/tlf-index.csv（図表の宣言。SAS系・R系・トレーサビリティ索引の3つが読む正本）の健全性を見る。
# 設計は docs/spec/tlf-declaration-design.md。
#
#   - 列の並びが SAS 側の input 文（%tlf_read）と同じか
#   - seq に重複・欠番が無いか
#   - 表番号が label-catalog の title に存在するか
#   - 解析ID・図表グループが ARD にあるか（Box のある端末だけ）
#   - 表示型が SAS 側（tlf_ops.sas のマクロ）と R 側（TLF.R の d_ 関数）の両方にあるか
#   - 表示型ごとに要る列が埋まっているか
#   - マクロ引数として渡せない文字（カンマ・セミコロン・& ・%）が値に無いか
#
# 2026-08-21 まではこの検査が TLF.sas の描画宣言と CSV を照合していた。SAS 側を CSV 駆動へ
# 変えて宣言の実体が1つになったので、照合はやめた。SAS のソースを読まないため、
# セッションの符号化を変えてもこの検査は壊れない。
import sys, os, csv, re, glob, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(REPO, 'docs', 'metadata', 'tlf-index.csv')
# 表示型の実装は汎用（tlf_ops.sas）と試験固有（tlf_ops_trial.sas）に分かれる。
# 片方だけを見ると、切り出した表示型が「SAS 側に無い」と誤って出る
SAS = sorted(glob.glob(os.path.join(REPO, 'program', 'sas', 'macro', 'tlf_ops*.sas')))
RSRC = os.path.join(REPO, 'program', 'r', boxpath.trial_id() + '_TLF.R')

# 列の並びは docs/metadata/tlf-index.csv が正本。SAS の %tlf_read（LENGTH 文と INPUT 文と
# 駆動の array）と R の read_csv が同じ並びを読むので、列を足したらこの4箇所を揃える。
# 1箇所でも漏れると、その列は宣言に書いても黙って効かない
COLS = ['seq', 'lblid', 'display', 'analysis_id', 'output_id', 'filter', 'groups',
        'levels', 'item_var', 'item_label', 'vars', 'labels', 'paramcd', 'where',
        'group', 'blocks', 'subtypemap']

# 表示型ごとに埋まっていなければならない列
REQ = {'tab_km': ['analysis_id'], 'tab_prop': ['analysis_id'], 'tab_cif': ['analysis_id'],
       'tab_prop_grp': ['analysis_id', 'groups', 'levels'],
       'tab_prop_grp_multi': ['output_id', 'groups', 'blocks'],
       'tab_prop_tp': ['output_id', 'levels'], 'tab_bg': ['output_id'],
       'tab_count': ['output_id'], 'tab_crs': ['output_id', 'levels'],
       'tab_aegr': ['output_id'], 'tab_list': ['vars', 'labels'],
       'tab_mrlist': [],
       # tab_ref は行の定義を docs/metadata/reference-table-rows.csv、文献値を reference-values.csv が持つ
       'tab_ref': [],
       'fig_km': ['paramcd']}

# マクロ呼び出しの引数として渡せない文字。区切りには | ~ : を使う
BAD = {',': 'カンマ', ';': 'セミコロン', '&': 'アンパサンド', '%': 'パーセント'}

err, warn = [], []

with open(IDX, encoding='utf-8-sig', newline='') as f:
    rd = csv.DictReader(f)
    head = rd.fieldnames
    idx = list(rd)

if head != COLS:
    err.append(f'列の並びが違う（CSV {head} / 期待 {COLS}）')

print(f'tlf-index.csv {len(idx)} 宣言')

seqs = [r['seq'] for r in idx]
dup = [k for k, v in collections.Counter(seqs).items() if v > 1]
if dup:
    err.append('seq の重複: ' + '、'.join(dup))
try:
    ns = sorted(int(s) for s in seqs)
    if ns != list(range(1, len(ns) + 1)):
        err.append(f'seq が 1 からの連番でない（{ns[0]} から {ns[-1]}、{len(ns)} 件）')
except ValueError:
    err.append('seq に数でない値がある')

# 表示型の実装（SAS のマクロと R の d_ 関数）
sas_disp = set()
for _p in SAS:
    sas_disp |= set(re.findall(r'^%macro\s+((?:tab|fig)_[a-z0-9_]+)\s*\(',
                               open(_p, encoding='utf-8').read(), re.M))
r_disp = set(re.findall(r'^d_((?:tab|fig)_[a-z0-9_]+)\s*<-\s*function',
                        open(RSRC, encoding='utf-8').read(), re.M))

# 表題（label-catalog の kind=title）
titles = set()
with open(os.path.join(REPO, 'docs', 'metadata', 'label-catalog.csv'), encoding='utf-8-sig',
          newline='') as f:
    for r in csv.DictReader(f):
        if r['kind'] == 'title':
            titles.add(r['key'])

for r in idx:
    lb = r['lblid']
    d = r['display']
    if d not in sas_disp:
        err.append(f'{lb} の表示型 {d} が SAS 側（tlf_ops.sas）に無い')
    if d not in r_disp:
        err.append(f'{lb} の表示型 {d} が R 側（TLF.R の d_{d}）に無い')
    for c in REQ.get(d, []):
        if not (r[c] or '').strip():
            err.append(f'{lb}（{d}）の {c} が空')
    if d not in REQ:
        warn.append(f'{lb} の表示型 {d} に必須列の定義が無い（REQ に足すこと）')
    if lb not in titles:
        warn.append(f'{lb} の表題が label-catalog に無い')
    for c in COLS:
        for ch, nm in BAD.items():
            if ch in (r[c] or ''):
                err.append(f'{lb} の {c} に{nm}がある（マクロ引数として渡せない）: {r[c]}')

box = boxpath.trial_dir(required=False)
if not box:
    print('Box が無いため ARD との突合は飛ばした')
else:
    p = os.path.join(box, 'datasets', 'sas', 'ard', 'ard_cards.csv')
    ids, outs = set(), set()
    if os.path.exists(p):
        with open(p, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                ids.add(r['analysis_id'])
                outs.add(r['output_id'])
    for r in idx:
        if r['analysis_id'] and r['analysis_id'] not in ids:
            warn.append(f"{r['lblid']} が指す解析 {r['analysis_id']} が ARD に無い")
        if r['output_id'] and r['output_id'] not in outs:
            warn.append(f"{r['lblid']} が指す図表グループ {r['output_id']} が ARD に無い")

    # tab_bg の行が一意に決まるか。item_var で選んだ軸だけでは行を区別できず、
    # 同じ行ラベルが並んでいた表が3つあった（Out-5.4.7.2・5.4.7.4・5.4.7.5。2026-08-23）。
    # 同じ (行項目, 水準) に複数の解析が当たるなら、item_var に軸を足す必要がある。
    rows_by_out = collections.defaultdict(list)
    with open(p, encoding='utf-8-sig', newline='') as f:
        for a in csv.DictReader(f):
            rows_by_out[a['output_id']].append(a)
    COL = {'VARIABLE': 'variable', 'GROUP1L': 'group1_level'}
    for r in idx:
        if r['display'] != 'tab_bg':
            continue
        axes = (r['item_var'] or 'VARIABLE').split('|')
        if any(v not in COL for v in axes):
            err.append(f"{r['lblid']} の item_var に未対応の軸がある: {r['item_var']}")
            continue
        seen = collections.defaultdict(set)
        for a in rows_by_out.get(r['output_id'], []):
            seen[tuple(a[COL[v]] for v in axes) + (a['variable_level'],)].add(a['analysis_id'])
        dup = {k: sorted(v) for k, v in seen.items() if len(v) > 1}
        if dup:
            k, v = next(iter(dup.items()))
            err.append(f"{r['lblid']}（tab_bg）の行が一意でない。item_var={r['item_var']} "
                       f"では {len(dup)} 組の行が重なる（例 {k} に {len(v)} 解析: "
                       f"{'、'.join(v[:3])}…）。item_var に軸を足すこと")

    # 水準の並び順（label-catalog の kind=level の order 列）の混在を止める。
    # 番号を入れるなら、その水準集合の全部に入れる。一部にしか無いと、番号の無い水準が
    # 欠測（SAS では最小値、R では 9999）として意図しない位置に来る（2026-08-23）。
    lvord = {}
    with open(os.path.join(REPO, 'docs', 'metadata', 'label-catalog.csv'), encoding='utf-8-sig',
              newline='') as f:
        for a in csv.DictReader(f):
            if a['kind'] == 'level':
                lvord[a['key']] = (a.get('order') or '').strip()
    sets = collections.defaultdict(set)
    with open(p, encoding='utf-8-sig', newline='') as f:
        for a in csv.DictReader(f):
            if a['context'] == 'categorical':
                sets[(a['analysis_id'], a['variable'], a['group1_level'])].add(
                    a['variable_level'])
    mixed = {}
    for k, lv in sets.items():
        has = {x for x in lv if lvord.get(x)}
        if has and has != lv:
            mixed[tuple(sorted(lv))] = (sorted(has), sorted(lv - has))
    for lv, (has, lack) in sorted(mixed.items()):
        err.append(f"水準 {'・'.join(lv)} は order が混在している"
                   f"（あり: {'・'.join(has)} / なし: {'・'.join(lack)}）。"
                   f"label-catalog.csv の kind=level に、この集合の全水準へ order を入れるか、"
                   f"1つも入れないかにすること")

print('表示型: ' + ' '.join(f'{k}={v}' for k, v in
                            collections.Counter(r['display'] for r in idx).most_common()))
for w in warn:
    print('WARN:', w)
for e in err:
    print('ERROR:', e)

# 表示文言のキーの名前空間。R の lvl() は kind=level と kind=bgitem を同じ名前空間で引く
# （SAS は水準を _lvcat、行項目を $bgitem 出力形式で分けている）。同じキーが両方にあると
# R だけが片方を拾い、SAS-R の突合で表示名の差として出る（2026-08-25 に CHR・CMR で発生）
_lab = os.path.join(REPO, 'docs', 'metadata', 'label-catalog.csv')
if os.path.exists(_lab):
    with open(_lab, encoding='utf-8-sig', newline='') as f:
        _rows = list(csv.DictReader(f))
    _lv = {r['key'] for r in _rows if r['kind'] == 'level'}
    _bg = {r['key'] for r in _rows if r['kind'] == 'bgitem'}
    _dup = sorted(_lv & _bg)
    if _dup:
        err.append('label-catalog.csv の kind=level と kind=bgitem で同じキーがある: '
                   + '・'.join(_dup)
                   + '（R の lvl() は同じ名前空間で引くので、どちらかを別名にすること）')

print(f'ERROR {len(err)} 件 / WARN {len(warn)} 件')
sys.exit(1 if err else 0)
