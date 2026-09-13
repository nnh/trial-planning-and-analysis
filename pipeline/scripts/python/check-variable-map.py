# check-variable-map.py
#
# docs/metadata/variable-map.csv の整合を確かめる。手で維持する正本なので、編集したら回す。
#   - layer / dataset / variable が一意か
#   - origin の値が CRF / Derived / Assigned / Predecessor / Protocol のいずれか
#   - origin=Predecessor なら predecessor が入っているか
#   - predecessor が指す変数が variable-map に実在するか（EXT. と RAW. は外部データなので除く）
#   - spec_ref のファイルが docs/ の下にあるか（同名が複数フォルダにあれば曖昧として挙げる）
#   - order がデータセットごとに 1..n の通番になっているか（adam は全件、sdtm は Trial Design）
#   - length が正の整数か
#
# ここまではリポジトリの中だけで見る。加えて Dataset-JSON（Box）と突き合わせ、
#   - 網羅：Dataset-JSON の変数集合と variable-map の行の集合が一致するか（片側だけの変数を挙げる）
#   - length：variable-map の宣言長が Dataset-JSON の length と一致するか
#   - order：order を持つデータセットで Dataset-JSON の列の並びと一致するか
# を見る。参照整合だけを見て網羅を見なかったため、2026-09-05 まで SDTM 1件（TV.TVSTRL）と
# ADSL 12件の欠落が検査に出ていなかった。
#
# 使い方
#   python scripts/check-variable-map.py               ... 参照整合と Dataset-JSON との突合
#   python scripts/check-variable-map.py --system r    ... 突合先を R 系の Dataset-JSON にする
#   python scripts/check-variable-map.py --allow-skip  ... Box が無ければ突合を飛ばして 0 で終える
#
# Box が無い端末では、何が無くて何を検査しなかったかを述べて非0で終える。材料が無いまま
# 0 を返すと、網羅を1件も見ずに検査が通る（check-visual-regression.py と同じ扱い。C3-124）。
#
# 責務の範囲は変数系譜の参照整合と変数属性の網羅に限る。図表の行数・信頼区間の方式・
# Excel チャートの描画は一切見ないので、これが通っても成果物の品質は何も保証されない。
# 検査一覧の区分は docs/validation/plan.md が持つ（C2-005）。
import sys, csv, os, re, json, glob, argparse, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

ap = argparse.ArgumentParser()
ap.add_argument('--system', choices=['sas', 'r'], default='sas',
                help='突き合わせる Dataset-JSON の実装系統（既定 sas）')
ap.add_argument('--allow-skip', action='store_true',
                help='Dataset-JSON が無ければ突合を行わずに終える')
ARGS = ap.parse_args()

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(REPO, 'docs', 'metadata', 'variable-map.csv')
DOCS = os.path.join(REPO, 'docs')
OK_ORIGIN = {'CRF', 'Derived', 'Assigned', 'Predecessor', 'Protocol'}


def docs_index():
    """docs/ 配下のファイルを基底名で引ける形にする。

    2026-08-25 に docs は直下へファイルを置かない構成へ移り、実体は spec/・metadata/・
    validation/records/ 等の下にある。spec_ref は基底名（`sdtm-spec.md`）で書かれているので、
    docs/<spec_ref> の直参照では必ず外れる。ここで横断して解決する。
    同名が複数フォルダにあり得るため、値は見つかった docs 相対パスの一覧にする。
    """
    idx = collections.defaultdict(list)
    for root, dirs, files in os.walk(DOCS):
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), DOCS).replace(os.sep, '/')
            idx[name].append(rel)
    return {k: sorted(v) for k, v in idx.items()}


DOCS_BY_NAME = docs_index()


def resolve_spec_ref(ref):
    """spec_ref を docs 相対パスへ解決する。(パス, エラー文言) を返す。

    値は「ファイル名＋節番号」の形（`adam-spec.md §1.2`・`ard-spec.md Out-5.2.1`・
    節番号なしの `ard-spec.md`）。節番号は build-spec-html.py が振る HTML の id 用で、
    ファイルの所在とは関係ないので落としてから照合する。
    フォルダ付き（`spec/efs-derivation.md`）で書かれている行もあるので、その場合は
    書かれたとおりに docs/ からたどる。
    """
    ref = ref.strip()
    if not ref:
        return '', ''
    path = ref.split()[0].strip()          # 節番号・output_id は空白の後ろにある
    if '/' in path or os.sep in path:      # フォルダまで書いてあるならそのまま見る
        return (path, '') if os.path.exists(os.path.join(DOCS, path)) \
            else ('', f'spec_ref のファイルが無い "{path}"')
    hits = DOCS_BY_NAME.get(path, [])
    if not hits:
        return '', f'spec_ref のファイルが docs/ に無い "{path}"'
    if len(hits) > 1:
        return '', f'spec_ref "{path}" が docs/ の複数に該当して曖昧: ' + ' / '.join(hits)
    return hits[0], ''


with open(P, encoding='utf-8-sig', newline='') as f:
    reader = csv.DictReader(f)
    header = reader.fieldnames or []
    rows = list(reader)
# 列が欠けていると以降が KeyError の traceback で落ちて、何が足りないのか読めない。
# 列の集合は正本の形なので、先に名前で確かめる。
missing_cols = [c for c in ('layer', 'dataset', 'variable', 'label_en', 'length',
                            'origin', 'predecessor', 'crf_sheet', 'crf_field',
                            'spec_ref', 'order') if c not in header]
if missing_cols:
    sys.exit(f'{P} に列が無い: ' + '・'.join(missing_cols))
print(f'{len(rows)} 行 / layer: ' + str(dict(collections.Counter(r['layer'] for r in rows))))
print('区分: 変数系譜の参照整合と変数属性の網羅。図表・信頼区間・Excel チャートは対象外')

err = []
key = collections.Counter((r['layer'], r['dataset'], r['variable']) for r in rows)
for k, v in key.items():
    if v > 1:
        err.append(f'重複: {k} が {v} 行')

known = {(r['dataset'], r['variable']) for r in rows}
for r in rows:
    where = f"{r['layer']}/{r['dataset']}.{r['variable']}"
    if r['origin'] not in OK_ORIGIN:
        err.append(f'{where}: origin が不正 "{r["origin"]}"')
    if r['origin'] == 'Predecessor' and not r['predecessor']:
        err.append(f'{where}: origin=Predecessor だが predecessor が空')
    for p in [x.strip() for x in r['predecessor'].split('/') if x.strip()]:
        if p.startswith(('EXT.', 'RAW.')):
            continue                       # 外部データ（engraftment.csv・saihi.csv 等）
        if '.' not in p:
            err.append(f'{where}: predecessor "{p}" が <dataset>.<variable> の形でない')
            continue
        ds, var = p.split('.', 1)
        if (ds, var) not in known:
            err.append(f'{where}: predecessor "{p}" が variable-map に無い')
    _, msg = resolve_spec_ref(r['spec_ref'])
    if msg:
        err.append(f'{where}: {msg}')
    if r['length'] and not (r['length'].isdigit() and int(r['length']) > 0):
        err.append(f'{where}: length が正の整数でない "{r["length"]}"')
    if r['order'] and not (r['order'].isdigit() and int(r['order']) > 0):
        err.append(f'{where}: order が正の整数でない "{r["order"]}"')

# order はデータセットごとに 1..n の通番。抜けや重複があると並びが決まらない。
# adam は全データセットが持つ。sdtm は標準の写し（external/sdtm_variable_order.csv）が
# 並びを定めるので原則は空で、標準が扱わない Trial Design の5ドメインだけ持つ
# （2026-09-05、段F。define.xml の ItemRef の並びがここから決まる）。
ds_order = collections.defaultdict(list)
for r in rows:
    if r['layer'] in ('adam', 'sdtm'):
        ds_order[(r['layer'], r['dataset'])].append(r['order'])
for (lay, ds), seq in sorted(ds_order.items()):
    if lay == 'sdtm' and not any(seq):
        continue                      # 標準の写しが並びを持つデータセット
    if '' in seq:
        err.append(f'{lay}/{ds}: order が空の行が {seq.count("")} 件')
        continue
    got = sorted(int(x) for x in seq)
    if got != list(range(1, len(seq) + 1)):
        err.append(f'{lay}/{ds}: order が 1..{len(seq)} の通番でない')

def report(title, msgs):
    """見つかったものを列挙する。ここでは終了しない。

    リポジトリの中だけで分かる不整合と Dataset-JSON との食い違いは同じ原因から出る
    （行の欠落は通番の穴としても網羅の穴としても現れる）。片方で止めると、もう片方が
    指し示す「どの変数が欠けているか」が見えないため、両方を出してから終える。
    """
    if not msgs:
        print(f'{title}: 指摘なし')
        return
    print(f'{title}: {len(msgs)} 件')
    for m in msgs[:60]:
        print('  ' + m)
    if len(msgs) > 60:
        print(f'  ... 他 {len(msgs) - 60} 件')


report('参照整合と列の値', err)
print('origin: ' + str(dict(collections.Counter(r['origin'] for r in rows))))

# ---------------------------------------------------------------------------------
# SDTM 層のラベルを SDTMIG 3.2 の写しと突き合わせる。
#
# ラベルの正本は variable-map.csv だが、値そのものは標準が定めるものである
# （docs/spec/sdtm-spec.md §2.2.2）。ここを見ていなかったため、QS.QSSTRESC だけ
# "Character Result/Finding in Standard Format" と手で書かれたまま 2026-09-05 まで残り、
# 他の6ドメインの --STRESC（"... in Std Format"）と食い違っていた。define.xml の生成が
# 同じ写しからラベルを採るので、ここがずれると define.xml と Dataset-JSON が食い違う。
# ADaM は IG が試験固有の変数のラベルを定めないので対象にしない。
# ---------------------------------------------------------------------------------
IG = os.path.join(DOCS, 'metadata', 'external', 'sdtmig-3-2-variable-roles.csv')
lerr = []
if not os.path.exists(IG):
    lerr.append(f'SDTMIG 3.2 の写しが無い（{IG}）')
else:
    with open(IG, encoding='utf-8-sig', newline='') as f:
        ig = {(r['domain'], r['variable']): r['label']
              for r in csv.DictReader(f) if r['label']}
    n_hit = 0
    for r in rows:
        if r['layer'] != 'sdtm':
            continue
        k = (r['dataset'], r['variable'])
        if k not in ig:
            lerr.append(f'sdtm/{k[0]}.{k[1]}: SDTMIG 3.2 の写しに無い変数')
            continue
        n_hit += 1
        if ig[k] != r['label_en']:
            lerr.append(f'sdtm/{k[0]}.{k[1]}: label_en が SDTMIG 3.2 と違う'
                        f'（CSV "{r["label_en"]}" / IG "{ig[k]}"）')
    print(f'sdtm: SDTMIG 3.2 の写しと照合した変数 {n_hit} 件')
report('SDTM のラベルと外部標準', lerr)
err += lerr

# ---------------------------------------------------------------------------------
# Dataset-JSON との突合（網羅・length・order）
#
# 既定の突き合わせ先は SAS 系の Dataset-JSON（`datasets/sas/{sdtm,adam}/json`）である。
# ラベル・宣言長・並びの正本は variable-map.csv（docs/spec/sdtm-spec.md §2.2.2・§2.2.3、
# docs/spec/adam-spec.md §11）だが、値の出どころは SAS が宣言していた属性なので、
# CSV へ固定した値が出どころと1件も違わないことをここで見る。
#
# `--system r` で R 系（`datasets/r/{sdtm,adam}/json`）を指せる。define.xml の生成が読むのは
# R 系なので、生成の前に掛けるときはそちらを指す（scripts/run-adam-validation.py）。宣言と
# 実データの照合は、生成が読むのと同じデータに対して行わなければ意味を持たない。SDTM 側の
# check-sdtm-declarations.py が `--json-dir` の既定を R 系にしているのと同じ考え方である。
# ---------------------------------------------------------------------------------
ALLOW_SKIP = ARGS.allow_skip
LAYER_DIR = {'sdtm': ('datasets', ARGS.system, 'sdtm', 'json'),
             'adam': ('datasets', ARGS.system, 'adam', 'json')}

lack = []
box = boxpath.trial_dir(required=False)
if not box:
    lack.append('Box の試験フォルダが見つからない（Dataset-JSON はその下にある）')
else:
    for lay, sub in LAYER_DIR.items():
        d = os.path.join(box, *sub)
        if not glob.glob(os.path.join(d, '*.json')):
            lack.append(f'{lay} の Dataset-JSON が無い（{d}）')
if lack:
    for x in lack:
        print('材料が無い:', x)
    if ALLOW_SKIP:
        print('--allow-skip のため網羅・length・order の突合を行わずに終える')
        sys.exit(1 if err else 0)
    print('網羅・length・order を1件も突き合わせていない。'
          '飛ばすなら --allow-skip を付ける')
    sys.exit(1)


def json_columns(directory):
    """Dataset-JSON の columns を {(dataset, variable): (length, 並びの番号)} で返す。

    ITEMGROUPDATASEQ は Dataset-JSON がレコード識別子として置く列であり、SDTM・ADaM の
    変数ではないので数えない。並びの番号は残りの変数だけで 1 から振る。
    """
    out = {}
    for f in sorted(glob.glob(os.path.join(directory, '*.json'))):
        with open(f, encoding='utf-8-sig') as fh:
            j = json.load(fh)
        n = 0
        for c in j['columns']:
            if c['name'] == 'ITEMGROUPDATASEQ':
                continue
            n += 1
            L = c.get('length')
            out[(j['name'], c['name'])] = ('' if L is None else str(L), n)
    return out


derr = []
for lay, sub in LAYER_DIR.items():
    js = json_columns(os.path.join(box, *sub))
    mp = {(r['dataset'], r['variable']): r for r in rows if r['layer'] == lay}
    for k in sorted(set(js) - set(mp)):
        derr.append(f'{lay}/{k[0]}.{k[1]}: Dataset-JSON にあるが variable-map に無い')
    for k in sorted(set(mp) - set(js)):
        derr.append(f'{lay}/{k[0]}.{k[1]}: variable-map にあるが Dataset-JSON に無い')
    for k in sorted(set(js) & set(mp)):
        length, order = js[k]
        if mp[k]['length'] != length:
            derr.append(f'{lay}/{k[0]}.{k[1]}: length が Dataset-JSON と違う'
                        f'（CSV "{mp[k]["length"]}" / JSON "{length}"）')
        # sdtm は order を持つデータセット（Trial Design）だけ見る。持たないものは
        # 標準の写しが並びを定めるので、空であることが正しい
        if (lay == 'adam' or (lay == 'sdtm' and mp[k]['order'])) \
                and mp[k]['order'] != str(order):
            derr.append(f'{lay}/{k[0]}.{k[1]}: order が Dataset-JSON の並びと違う'
                        f'（CSV "{mp[k]["order"]}" / JSON {order}）')
    print(f'{lay}: Dataset-JSON（{ARGS.system} 系）{len(js)} 変数 / variable-map {len(mp)} 行')

report('網羅・length・order', derr)
sys.exit(1 if (err or derr) else 0)
