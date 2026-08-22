# check-tlf-index.py
#
# docs/tlf-index.csv（図表の宣言。SAS系・R系・追跡索引の3つが読む正本）の健全性を見る。
# 設計は docs/tlf-declaration-design.md。
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
import sys, os, csv, re, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(REPO, 'docs', 'tlf-index.csv')
SAS = os.path.join(REPO, 'program', 'macro', 'tlf_ops.sas')
RSRC = os.path.join(REPO, 'program', 'r', boxpath.trial_id() + '_TLF.R')

COLS = ['seq', 'lblid', 'display', 'analysis_id', 'output_id', 'filter', 'groups',
        'levels', 'item_var', 'item_label', 'vars', 'labels', 'paramcd', 'where',
        'group', 'blocks']

# 表示型ごとに埋まっていなければならない列
REQ = {'tab_km': ['analysis_id'], 'tab_prop': ['analysis_id'], 'tab_cif': ['analysis_id'],
       'tab_prop_grp': ['analysis_id', 'groups', 'levels'],
       'tab_prop_grp_multi': ['output_id', 'groups', 'blocks'],
       'tab_prop_tp': ['output_id', 'levels'], 'tab_bg': ['output_id'],
       'tab_count': ['output_id'], 'tab_crs': ['output_id', 'levels'],
       'tab_aegr': ['output_id'], 'tab_list': ['vars', 'labels'],
       'tab_mrlist': [], 'fig_km': ['paramcd']}

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
sas_disp = set(re.findall(r'^%macro\s+((?:tab|fig)_[a-z0-9_]+)\s*\(',
                          open(SAS, encoding='utf-8').read(), re.M))
r_disp = set(re.findall(r'^d_((?:tab|fig)_[a-z0-9_]+)\s*<-\s*function',
                        open(RSRC, encoding='utf-8').read(), re.M))

# 表題（label-catalog の kind=title）
titles = set()
with open(os.path.join(REPO, 'docs', 'label-catalog.csv'), encoding='utf-8-sig',
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
    p = os.path.join(box, 'input', 'ads', 'ard_cards.csv')
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

print('表示型: ' + ' '.join(f'{k}={v}' for k, v in
                            collections.Counter(r['display'] for r in idx).most_common()))
for w in warn:
    print('WARN:', w)
for e in err:
    print('ERROR:', e)
print(f'ERROR {len(err)} 件 / WARN {len(warn)} 件')
sys.exit(1 if err else 0)
