# check-crf-field-map.py
#
# docs/crf-field-map.csv・docs/crf-option-map.csv（Ptosh の eCRF 定義から生成）の整合を
# 確かめる。生成物なので手で直さない。ここで出る指摘は Ptosh の定義か variable-map を直す。
#
#   - (sheet_slug, field_name) が一意か
#   - sdtm_variable が variable-map の sdtm / pv 層に実在するか（ドメインまで一致するか）
#   - 参照先の origin が CRF になっているか（Ptosh と variable-map の食い違い）
#   - variable-map で origin=CRF なのに CRF のどの項目からも指されない変数（追跡の切れ目）
#   - レコード（帳票×レコード番号×ドメイン）に --TESTCD 等の識別変数が入っているか
#   - option_name が crf-option-map.csv に実在するか
#   - reference_field の参照先の項目が実在するか
#   - 帳票スラッグが --SPID の実値に現れるか（Box がある端末でだけ実施）
import sys, os, csv, glob, re, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name):
    with open(os.path.join(REPO, 'docs', name), encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


rows = load('crf-field-map.csv')
opts = load('crf-option-map.csv')
vm = load('variable-map.csv')

kind = collections.Counter(r['field_kind'] for r in rows)
recs = {(r['sheet_slug'], r['record_label'], r['sdtm_domain']) for r in rows if r['record_label']}
print(f'{len(rows)} 行 / 帳票 {len({r["sheet_slug"] for r in rows})} / '
      f'SDTM レコード {len(recs)} / 種別 ' + str(dict(kind)))

err, warn = [], []

key = collections.Counter((r['sheet_slug'], r['field_name']) for r in rows)
for k, v in key.items():
    if v > 1:
        err.append(f'重複: {k} が {v} 行')

have = collections.defaultdict(set)
origin = {}
for r in vm:
    if r['layer'] in ('sdtm', 'pv'):
        have[r['dataset']].add(r['variable'])
        origin[(r['dataset'], r['variable'])] = r['origin']

mapped = [r for r in rows if r['sdtm_variable']]
for r in mapped:
    ds, v = r['sdtm_domain'], r['sdtm_variable']
    if v not in have.get(ds, ()):
        err.append(f'{r["sheet_slug"]}#{r["field_name"]}: {ds}.{v} が variable-map に無い')
        continue
    if r['field_kind'] == 'article' and origin.get((ds, v)) != 'CRF':
        warn.append(f'{r["sheet_slug"]}#{r["field_name"]}: 入力欄が {ds}.{v} に入るが '
                    f'variable-map の origin は {origin.get((ds, v))}')

pointed = {(r['sdtm_domain'], r['sdtm_variable']) for r in mapped}
for (ds, v), o in origin.items():
    if o == 'CRF' and (ds, v) not in pointed:
        warn.append(f'origin=CRF だが CRF のどの項目からも指されない: {ds}.{v}')

# レコードに識別変数（--TESTCD・--OBJ・--TRT・--TERM・--DECOD）が入っているか。
# これが無いレコードは、同じドメインの他のレコードと区別する手掛かりが CRF 側に無い。
byrec = collections.defaultdict(list)
for r in mapped:
    byrec[(r['sheet_slug'], r['record_label'], r['sdtm_domain'])].append(r)
IDSUF = ('TESTCD', 'OBJ', 'TRT', 'TERM', 'DECOD', 'SPID', 'PARM')
noid = [k for k, rs in byrec.items()
        if not any(r['sdtm_variable'].endswith(IDSUF) for r in rs)]
if noid:
    warn.append(f'識別変数を持たないレコード {len(noid)} 件: '
                + '、'.join(f'{a}/{b}/{c}' for a, b, c in sorted(noid)[:8]))

optnames = {o['option_name'] for o in opts}
for r in rows:
    if r['option_name'] and r['option_name'] not in optnames:
        err.append(f'{r["sheet_slug"]}#{r["field_name"]}: 選択肢セット '
                   f'「{r["option_name"]}」が crf-option-map に無い')

exists = {(r['sheet_slug'], r['field_name']) for r in rows}
for r in rows:
    t = r['reference_field']
    if not t:
        continue
    if '.' not in t:
        err.append(f'{r["sheet_slug"]}#{r["field_name"]}: 参照先の書式が不明「{t}」')
        continue
    sl, fn = t.split('.', 1)
    if (sl, fn) not in exists:
        warn.append(f'{r["sheet_slug"]}#{r["field_name"]}: 参照先 {t} が見つからない'
                    '（画面に出ない項目を参照している可能性）')

box = boxpath.trial_dir(required=False)
if not box:
    print('Box が見つからないため --SPID 実値との突合は飛ばした')
else:
    spid = set()
    for p in sorted(glob.glob(os.path.join(box, 'input', 'rawdata', '*.csv'))):
        with open(p, encoding='utf-8-sig', newline='') as f:
            rd = csv.DictReader(f)
            cols = [c for c in (rd.fieldnames or []) if c.endswith('SPID')]
            if not cols:
                continue
            for x in rd:
                v = (x[cols[0]] or '').strip()
                if v:
                    spid.add(v)
    slugs = {r['sheet_slug'] for r in rows}

    def base(s):
        return re.sub(r'\d*(-[A-Z])?$', '', s)

    unmatched = sorted(s for s in spid if s not in slugs and base(s) not in slugs)
    nospid = sorted(s for s in slugs if s not in spid and
                    not any(base(v) == s for v in spid))
    print(f'--SPID 実値 {len(spid)} 種 / 帳票へ対応しない実値 {len(unmatched)} / '
          f'実値に現れない帳票 {len(nospid)}')
    if unmatched:
        print('  対応しない実値: ' + '、'.join(unmatched))
    if nospid:
        print('  実値に現れない帳票: ' + '、'.join(nospid))

for w in warn:
    print('WARN:', w)
for e in err:
    print('ERROR:', e)
print(f'ERROR {len(err)} 件 / WARN {len(warn)} 件')
sys.exit(1 if err else 0)
