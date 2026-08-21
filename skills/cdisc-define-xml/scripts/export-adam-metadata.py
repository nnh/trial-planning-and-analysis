"""ADaM IG の変数ごとの Core とラベルを CSV に落とす。

ADaM の define.xml を作るとき、変数の Core（Required / Conditionally Required /
Permissible）とラベルは ADaM IG が定める。手で持つとハードコードになり、版が変わると
ずれる。CDISC CORE のキャッシュ（元は CDISC Library）から引く。

ADaM IG は SDTM と構造が違う。**データセットごとではなく変数グループごと**に定義されて
いて（`ADSL Identifier Variables`・`Timing Variables for BDS Datasets` など23グループ）、
どのデータセットにどのグループが当たるかは実装側が決める。したがってこの CSV は
「変数名 → Core・ラベル」の辞書として使う。データセットの区別は持たない。

**変数名にパターンが入る。** `DOSExxP`（xx は期の番号）・`SITEGRy`（y は分類の番号）・
`PARAMzz` のような形で、実データの変数名は `DOSE01P`・`SITEGR1` になる。CSV には
`variable`（IG の表記）と `regex`（照合用）の両方を出す。引くときは完全一致を先に見て、
無ければ regex で照合する。

    python export-adam-metadata.py --out docs/adamig-1-1-variables.csv
                                   [--version 1-1] [--cache <dir>]
"""
import argparse
import csv
import os
import pickle
import re
import sys
from collections import Counter

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

DEFAULT_CACHE = os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')),
                             'opt', 'cdisc-core', 'core', 'resources', 'cache')

# IG の変数名に現れるパターン。長いものから置き換える。
PATTERNS = [
    ('zzz', r'\d{1,3}'),
    ('xx', r'\d{1,2}'),
    ('zz', r'\d{1,2}'),
    ('yy', r'\d{1,2}'),
    ('w', r'\d+'),
    ('y', r'\d+'),
]


def to_regex(name):
    """IG の変数名を照合用の正規表現にする。パターンが無ければ None。"""
    out = name
    hit = False
    for pat, rex in PATTERNS:
        if pat in out:
            out = out.replace(pat, '\x00' + rex + '\x00')
            hit = True
    if not hit:
        return None
    # プレースホルダの外側だけをエスケープする
    parts = out.split('\x00')
    built = ''.join(p if i % 2 else re.escape(p) for i, p in enumerate(parts))
    return '^' + built + '$'


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', required=True, help='出力する CSV のパス')
    ap.add_argument('--version', default='1-1', help='ADaM IG の版（既定 1-1）')
    ap.add_argument('--cache', default=DEFAULT_CACHE)
    a = ap.parse_args()

    p = os.path.join(a.cache, 'variables_metadata.pkl')
    if not os.path.exists(p):
        raise SystemExit(f'CORE のキャッシュがありません: {p}')
    with open(p, 'rb') as f:
        meta = pickle.load(f)
    key = f'library_variables_metadata/adam/adamig-{a.version}'
    if key not in meta:
        avail = sorted(k for k in meta if '/adam/' in k)
        raise SystemExit(f'{key} がありません。あるのは:\n  ' + '\n  '.join(avail))
    ig = meta[key]
    print(f'ADaM IG {a.version} : {len(ig)} グループ')

    rows = []
    for group in sorted(ig):
        for name, v in ig[group].items():
            if not isinstance(v, dict):
                continue
            rows.append({'group': group, 'variable': name,
                         'regex': to_regex(name) or '',
                         'core': v.get('core') or '',
                         'label': v.get('label') or ''})
    # 同じ変数名が複数グループに出ることがある。完全一致を先に並べる
    rows.sort(key=lambda r: (bool(r['regex']), r['variable'], r['group']))

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or '.', exist_ok=True)
    with open(a.out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['group', 'variable', 'regex', 'core', 'label'])
        w.writeheader()
        w.writerows(rows)
    print(f'{a.out} を書いた（{len(rows)} 行）')

    print('Core の分布:')
    for k, n in Counter(r['core'] for r in rows).most_common():
        print(f'  {k or "(空)":10} {n}')
    npat = sum(1 for r in rows if r['regex'])
    print(f'パターンを含む変数: {npat} / {len(rows)}')
    print('パターンの例:')
    for r in [x for x in rows if x['regex']][:6]:
        print(f'  {r["variable"]:12} → {r["regex"]}')
    dup = {k: n for k, n in Counter(r['variable'] for r in rows).items() if n > 1}
    if dup:
        print(f'複数のグループに出る変数: {len(dup)} 種'
              f'（引くときは最初に見つかったものを使う）')
        for k in list(dup)[:6]:
            gs = [r['group'] for r in rows if r['variable'] == k]
            print(f'  {k:12} {", ".join(gs[:3])}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
