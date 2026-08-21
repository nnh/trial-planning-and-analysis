"""SDTM IG の変数メタデータ（Role・Core・ラベル）を CSV に落とす。

define.xml の `ItemRef/@Role` は SDTM IG が定める Role と一致していなければならない
（CDISC CORE の CORE-001081）。受領 define.xml は Role を持たないことが多いので、
define.xml を作る側がこの CSV を読んで付ける。ラベルの補完にも使う。

Role の出どころは2つある。

  IG のドメイン変数    … 各ドメインの変数リスト（AETERM・LBTESTCD など）
  モデルのクラス変数   … クラス共通の変数（EPOCH・VISIT・--DY・--SEQ など）。IG の
                         ドメイン変数リストには載らない。`--` はドメインのプレフィックス
                         に展開する

正本は CDISC Library で、その写しが CDISC CORE のキャッシュにある。ここではキャッシュから
読む。CORE が入っていない端末でも define.xml を作れるようにするため CSV を経由する。

    python export-sdtm-metadata.py --out docs/sdtmig-3-2-variable-roles.csv \
                                   [--domains AE,CM,...] [--domains-from <csv>] \
                                   [--version 3-2] [--model 1-4] [--cache <dir>]

対象ドメインは `--domains` で明示するか、`--domains-from` に `memname` 列（または
`dataset`・`domain` 列）を持つ CSV を渡す。どちらも省くと IG の全ドメインを出す。
"""
import argparse
import csv
import os
import pickle
import sys
from collections import Counter

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

DEFAULT_CACHE = os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')),
                             'opt', 'cdisc-core', 'core', 'resources', 'cache')

# クラスごとに、そのドメインへ適用するモデルのクラスの並び（後のものが優先）。
# Findings About は Findings を継承する。Trial Design と Relationship は被験者の観測では
# ないので General Observations（Timing・Identifier の共通変数）を継承しない。
CLASS_CHAIN = {
    'Special-Purpose': ['General Observations'],
    'Interventions':   ['General Observations', 'Interventions'],
    'Events':          ['General Observations', 'Events'],
    'Findings':        ['General Observations', 'Findings'],
    'Findings About':  ['General Observations', 'Findings', 'Findings About'],
    'Trial Design':    [],
    'Relationship':    [],
}


def load(cache, name):
    p = os.path.join(cache, name)
    if not os.path.exists(p):
        raise SystemExit(f'CORE のキャッシュがありません: {p}\n'
                         '--cache でディレクトリを指定してください。')
    with open(p, 'rb') as f:
        return pickle.load(f)


# CDISC Library の SDTMIG 3-2 には変数ラベルの誤記がある。紙の IG の表記に直す。
# 直さないと誤ったラベルが define.xml と Dataset-JSON に流れ、CORE-000594（ラベルが
# title case でない）が立つ。補正したことは必ず表示して、写しに手を入れた箇所を
# 追えるようにする。キーは (ドメイン, 変数)、値は (Library の値, 正しい値)。
# SDTM は変数ラベルを40文字以内と定めるが、Library には超えるものが3つある
# （FA.FALAT 43字・MH.MHREASND 47字・QS.QSSTRESC 43字）。うち QSSTRESC は他の6ドメインが
# すべて 'Character Result/Finding in Std Format' なので誤りと判断できる。残る2つは
# 短縮後の表記の根拠が無いため直さない（CORE-000019 が立ったら個別に判断する）。
LABEL_FIXES = {
    ('TI', 'IETESTCD'): ('Incl/Excl Criterion Short Name e',
                         'Incl/Excl Criterion Short Name'),
    ('QS', 'QSSTRESC'): ('Character Result/Finding in Standard Format',
                         'Character Result/Finding in Std Format'),
}


def domains_from_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit(f'{path} が空です')
    for col in ('memname', 'dataset', 'domain', 'DATASET', 'DOMAIN'):
        if col in rows[0]:
            return sorted({r[col].strip().upper() for r in rows if r[col].strip()})
    raise SystemExit(f'{path} に memname / dataset / domain の列がありません')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', required=True, help='出力する CSV のパス')
    ap.add_argument('--version', default='3-2', help='SDTM IG の版（既定 3-2）')
    ap.add_argument('--model', default='1-4', help='SDTM モデルの版（既定 1-4。IG 3.2 に対応）')
    ap.add_argument('--domains', help='カンマ区切りのドメイン')
    ap.add_argument('--domains-from', help='memname / dataset / domain 列を持つ CSV')
    ap.add_argument('--cache', default=DEFAULT_CACHE)
    a = ap.parse_args()

    details = load(a.cache, 'standards_details.pkl')
    models = load(a.cache, 'standards_models.pkl')
    varmeta = load(a.cache, 'variables_metadata.pkl')

    igkey = f'standards/sdtmig/{a.version}'
    mkey = f'models/sdtm/{a.model}'
    vkey = f'library_variables_metadata/sdtmig/{a.version}'
    for k, d in ((igkey, details), (mkey, models), (vkey, varmeta)):
        if k not in d:
            raise SystemExit(f'{k} がキャッシュにありません')

    classOf = {}
    for c in details[igkey]['classes']:
        for ds in (c.get('datasets') or []):
            if isinstance(ds, dict) and ds.get('name'):
                classOf[ds['name'].upper()] = c.get('name')

    modelVars = {}
    for c in models[mkey]['classes']:
        modelVars[c.get('name')] = [v for v in (c.get('classVariables') or [])
                                    if isinstance(v, dict) and v.get('name')]

    igVars = varmeta[vkey]

    if a.domains:
        doms = [d.strip().upper() for d in a.domains.split(',') if d.strip()]
    elif a.domains_from:
        doms = domains_from_csv(a.domains_from)
        print(f'対象ドメインは {os.path.basename(a.domains_from)} から: {" ".join(doms)}')
    else:
        doms = sorted(igVars)
        print(f'ドメインの指定が無いので IG の全 {len(doms)} ドメインを出す')

    rows = []
    for dom in doms:
        cls = classOf.get(dom)
        seen = {}
        for cname in CLASS_CHAIN.get(cls, ['General Observations']):
            for v in modelVars.get(cname, []):
                nm = v['name']
                nm = dom + nm[2:] if nm.startswith('--') else nm
                seen[nm] = {'domain': dom, 'variable': nm, 'role': v.get('role') or '',
                            'core': v.get('core') or '', 'label': v.get('label') or '',
                            'ordinal': '', 'source': f'model:{cname}'}
        for nm, v in (igVars.get(dom) or {}).items():
            if not isinstance(v, dict):
                continue
            seen[nm] = {'domain': dom, 'variable': nm, 'role': v.get('role') or '',
                        'core': v.get('core') or '', 'label': v.get('label') or '',
                        'ordinal': v.get('ordinal') or '', 'source': 'IG'}
        if cls is None:
            print(f'  {dom}: IG のクラスに属さない（モデルの共通変数だけ出す）')
        rows += list(seen.values())

    nfix = 0
    for r in rows:
        fx = LABEL_FIXES.get((r['domain'], r['variable']))
        if fx and r['label'] == fx[0]:
            r['label'] = fx[1]
            nfix += 1
            print(f'  ラベルを補正: {r["domain"]}.{r["variable"]} '
                  f'{fx[0]!r} → {fx[1]!r}')
    if nfix:
        print(f'CDISC Library の既知の誤記を {nfix} 件補正した')

    rows.sort(key=lambda r: (r['domain'],
                             int(r['ordinal']) if str(r['ordinal']).isdigit() else 9999,
                             r['variable']))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or '.', exist_ok=True)
    with open(a.out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['domain', 'variable', 'role', 'core',
                                          'label', 'ordinal', 'source'])
        w.writeheader()
        w.writerows(rows)
    print(f'{a.out} を書いた（{len(rows)} 行 / {len({r["domain"] for r in rows})} ドメイン）')

    print('Role の分布:')
    for k, n in Counter(r['role'] for r in rows).most_common():
        print(f'  {k or "(空)":22} {n}')
    print('Core の分布:')
    for k, n in Counter(r['core'] for r in rows).most_common():
        print(f'  {k or "(空)":22} {n}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
