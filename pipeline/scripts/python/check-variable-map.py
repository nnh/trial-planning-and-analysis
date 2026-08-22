# check-variable-map.py
#
# docs/variable-map.csv の整合を確かめる。手で維持する正本なので、編集したら回す。
#   - layer / dataset / variable が一意か
#   - origin の値が CRF / Derived / Assigned / Predecessor / Protocol のいずれか
#   - origin=Predecessor なら predecessor が入っているか
#   - predecessor が指す変数が variable-map に実在するか（EXT. と RAW. は外部データなので除く）
#   - spec_ref のファイルが docs/ にあるか
import sys, csv, os, re, collections
sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(REPO, 'docs', 'variable-map.csv')
OK_ORIGIN = {'CRF', 'Derived', 'Assigned', 'Predecessor', 'Protocol'}

with open(P, encoding='utf-8-sig', newline='') as f:
    rows = list(csv.DictReader(f))
print(f'{len(rows)} 行 / layer: ' + str(dict(collections.Counter(r['layer'] for r in rows))))

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
    ref = r['spec_ref'].split()[0].strip() if r['spec_ref'] else ''
    if ref and not os.path.exists(os.path.join(REPO, 'docs', ref)):
        err.append(f'{where}: spec_ref のファイルが無い "{ref}"')

if err:
    print(f'{len(err)} 件の不整合:')
    for e in err[:60]:
        print('  ' + e)
    if len(err) > 60:
        print(f'  ... 他 {len(err) - 60} 件')
    sys.exit(1)
print('不整合なし')
print('origin: ' + str(dict(collections.Counter(r['origin'] for r in rows))))
