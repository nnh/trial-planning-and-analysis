"""CDISC Controlled Terminology のコードリストを CSV に落とす。

define.xml の CodeList は、値そのもの（`CodedValue`）だけでなく NCI の C コードを
`Alias/@Name` に持つ。CORE は Alias を見て CT との一致を検査するため（`CORE-000929` は
DOMAIN の Alias を見る）、Alias が欠けていると「CT に無い値」として指摘される。
`Decode` を載せるときの表示名も CT の `preferredTerm` が正本になる。

CT の正本は CDISC Library で、その写しが CDISC CORE のキャッシュ（`sdtmct-<日付>.pkl`）に
ある。ここから読む。CORE が入っていない端末でも define.xml を作れるように CSV を経由する。

    python export-ct-codelist.py --out docs/ct-domain.csv --codelist C66734
    python export-ct-codelist.py --out docs/ct-all.csv          # 全コードリスト
    python export-ct-codelist.py --list                          # 何があるかを見る

`--codelist` は NCI の C コード（`C66734`）でも提出値（`DOMAIN`）でも名前の一部
（`Domain Abbreviation`）でも指す。複数はカンマで並べる。

定義文（`definition`）は長く CSV を膨らませるので既定では出さない。`--with-definition`
を付けると出す。
"""
import argparse
import csv
import glob
import os
import pickle
import sys
from collections import Counter

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

DEFAULT_CACHE = os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')),
                             'opt', 'cdisc-core', 'core', 'resources', 'cache')


def find_package(cache, name):
    """CT のパッケージファイルを決める。name 省略時は日付が最も新しいものを使う。"""
    if name:
        p = os.path.join(cache, name if name.endswith('.pkl') else f'{name}.pkl')
        if not os.path.exists(p):
            raise SystemExit(f'ありません: {p}')
        return p
    cands = sorted(glob.glob(os.path.join(cache, 'sdtmct-*.pkl')))
    if not cands:
        raise SystemExit(f'{cache} に sdtmct-*.pkl がありません')
    return cands[-1]


def matches(cl, key):
    """コードリストが key に該当するか。C コード・提出値・名前の一部で照合する。"""
    k = key.strip().upper()
    return (cl.get('conceptId', '').upper() == k
            or (cl.get('submissionValue') or '').upper() == k
            or k in (cl.get('name') or '').upper())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', help='出力する CSV のパス（--list のときは不要）')
    ap.add_argument('--codelist', help='C コード・提出値・名前の一部。カンマ区切りで複数')
    ap.add_argument('--package', help='CT のパッケージ名（既定は cache の最新）')
    ap.add_argument('--with-definition', action='store_true', help='定義文も出す')
    ap.add_argument('--list', action='store_true', help='コードリストの一覧を表示して終わる')
    ap.add_argument('--cache', default=DEFAULT_CACHE)
    a = ap.parse_args()

    p = find_package(a.cache, a.package)
    with open(p, 'rb') as f:
        d = pickle.load(f)
    cls = d['codelists']
    print(f'{os.path.basename(p)} : {len(cls)} コードリスト')

    if a.list:
        for cl in sorted(cls, key=lambda x: x.get('submissionValue') or ''):
            print(f"  {cl['conceptId']:10} {(cl.get('submissionValue') or ''):24} "
                  f"{len(cl.get('terms') or []):5} 語  {cl.get('name')}")
        return 0

    if not a.out:
        raise SystemExit('--out が要ります（一覧を見るだけなら --list）')

    keys = [k for k in (a.codelist or '').split(',') if k.strip()]
    if keys:
        sel = [cl for cl in cls if any(matches(cl, k) for k in keys)]
        if not sel:
            raise SystemExit(f'該当するコードリストがありません: {a.codelist}')
        print(f'対象: {", ".join(c["conceptId"] + " " + (c.get("submissionValue") or "") for c in sel)}')
    else:
        sel = cls
        print(f'コードリストの指定が無いので全 {len(sel)} 件を出す')

    cols = ['codelist_ccode', 'codelist_submission', 'codelist_name', 'extensible',
            'code', 'submission_value', 'preferred_term', 'synonyms']
    if a.with_definition:
        cols.append('definition')
    rows = []
    for cl in sel:
        for t in cl.get('terms') or []:
            r = {'codelist_ccode': cl.get('conceptId'),
                 'codelist_submission': cl.get('submissionValue') or '',
                 'codelist_name': cl.get('name') or '',
                 'extensible': 'Yes' if cl.get('extensible') else 'No',
                 'code': t.get('conceptId'),
                 'submission_value': t.get('submissionValue') or '',
                 'preferred_term': t.get('preferredTerm') or '',
                 'synonyms': '; '.join(t.get('synonyms') or [])}
            if a.with_definition:
                r['definition'] = (t.get('definition') or '').replace('\n', ' ')
            rows.append(r)
    rows.sort(key=lambda r: (r['codelist_submission'], r['submission_value']))

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or '.', exist_ok=True)
    with open(a.out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f'{a.out} を書いた（{len(rows)} 行 / {len({r["codelist_ccode"] for r in rows})} コードリスト）')

    nonascii = [r for r in rows
                if any(ord(ch) > 127 for ch in r['submission_value'] + r['preferred_term'])]
    if nonascii:
        print(f'注意: 非 ASCII を含む語が {len(nonascii)} 件（{nonascii[0]["submission_value"]!r} など）')
    if not keys:
        print('語数の多いコードリスト:')
        for k, n in Counter(r['codelist_submission'] for r in rows).most_common(5):
            print(f'  {k:24} {n}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
