"""臨床試験データセットの文字集合を検査する。

SDTM・ADaM を ASCII 印字可能文字（U+0020〜U+007E）だけで構成できているかを調べ、
外れた値を変数ごとに報告する。あわせて CP932（Windows-31J）にはあるが JIS X 0208
には無い文字を挙げる。これらは Shift_JIS を厳密に実装した処理系で別の文字になるか
読めなくなるため、日本の試験データを海外のツールへ渡すときに問題になる。

Dataset-JSON（v1.0/v1.1）・CSV・sas7bdat を読む。共有先が受け取るファイルで判定
したいので、通常は Dataset-JSON を対象にする。

    # 標準的なフォルダ構成を仮定する（datasets/<系統>/sdtm/json と datasets/<系統>/adam/json）
    python check-nonascii.py --root "<データルート>" [--system r|sas]

    # 対象を明示する（ディレクトリでもファイルでもよい。ラベル=パス）
    python check-nonascii.py --dir SDTM=<path>/sdtm/json --dir ADaM=<path>/adam/json
    python check-nonascii.py --file CO=<path>/sdtm/co.sas7bdat

    # 許容する変数（データセット.変数）を挙げる。理由は呼び出し側の文書に書く
    python check-nonascii.py --root "<データルート>" --allow CO.COVAL

終了コードは、許容していない非 ASCII の値が1件でもあれば 1、無ければ 0。
"""
import argparse
import csv
import json
import os
import sys
import unicodedata
from collections import Counter

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ASCII_OK = set(range(0x20, 0x7f))

# --root で探す標準構成（pipeline/analysis-pipeline-plan.md「フォルダ構成と命名規則」の
# datasets/<系統>/<層>/json）。存在するものだけを対象にする。二重コーディングの試験でも
# 共有先が受け取るのは正本の系統だけなので、系統は1つに絞る。どちらが正本かは試験が
# 決めることなので、両系統があるときは推測せず --system を求める。両方を見たいときは
# --dir で明示する。
SYSTEMS = ('r', 'sas')
DEFAULT_LAYERS = [
    ('SDTM', 'sdtm'),
    ('ADaM', 'adam'),
]


def default_dirs(root, system):
    return [(label, os.path.join(root, 'datasets', system, layer, 'json'))
            for label, layer in DEFAULT_LAYERS]


def has_nonascii(v):
    return isinstance(v, str) and any(ord(ch) not in ASCII_OK for ch in v)


def read_dataset_json(path):
    """Dataset-JSON を (データセット名, 列名リスト, 行のリスト) で返す。"""
    with open(path, encoding='utf-8-sig') as f:
        j = json.load(f)
    cols = [c.get('name') for c in j.get('columns', [])]
    name = j.get('name') or os.path.splitext(os.path.basename(path))[0].upper()
    return name, cols, j.get('rows', [])


def read_csv_file(path):
    for enc in ('utf-8-sig', 'cp932'):
        try:
            with open(path, encoding=enc, newline='') as f:
                rows = list(csv.reader(f))
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit(f'文字コードを判定できない: {path}')
    if not rows:
        return os.path.splitext(os.path.basename(path))[0].upper(), [], []
    return os.path.splitext(os.path.basename(path))[0].upper(), rows[0], rows[1:]


def read_sas7bdat(path):
    try:
        import pyreadstat
    except ImportError:
        raise SystemExit('sas7bdat を読むには pyreadstat が必要（pip install pyreadstat）')
    df, _ = pyreadstat.read_sas7bdat(path)
    name = os.path.splitext(os.path.basename(path))[0].upper()
    return name, list(df.columns), df.values.tolist()


READERS = {'.json': read_dataset_json, '.csv': read_csv_file, '.sas7bdat': read_sas7bdat}


def scan_file(path, layer):
    ext = os.path.splitext(path)[1].lower()
    reader = READERS.get(ext)
    if reader is None:
        return []
    name, cols, rows = reader(path)
    out = []
    for row in rows:
        for nm, v in zip(cols, row):
            if has_nonascii(v):
                out.append((layer, name, nm, v))
    return out


def scan_target(label, path):
    """ディレクトリなら中の読める全ファイル、ファイルならそれ1つを読む。"""
    if os.path.isdir(path):
        cells = []
        found = 0
        for fn in sorted(os.listdir(path)):
            if os.path.splitext(fn)[1].lower() in READERS:
                cells += scan_file(os.path.join(path, fn), label)
                found += 1
        if found == 0:
            print(f'  {label}: 読める形式のファイルが無い（{path}）')
        return cells
    if os.path.isfile(path):
        return scan_file(path, label)
    print(f'  {label}: {path} がありません')
    return []


def encodable(ch, enc):
    try:
        ch.encode(enc)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', help='データルート。標準構成のフォルダを探す')
    ap.add_argument('--system', choices=SYSTEMS,
                    help='--root で見る実装系統。datasets/ に系統が1つだけなら省略できる')
    ap.add_argument('--dir', action='append', default=[], metavar='ラベル=パス',
                    help='検査するディレクトリ。複数指定できる')
    ap.add_argument('--file', action='append', default=[], metavar='ラベル=パス',
                    help='検査するファイル。複数指定できる')
    ap.add_argument('--allow', action='append', default=[], metavar='DS.VAR',
                    help='非 ASCII を許容する変数。複数指定できる')
    ap.add_argument('--max-cells', type=int, default=5, help='変数ごとに表示する値の件数')
    ap.add_argument('--chars-only', action='store_true', help='文字種の一覧だけを出す')
    a = ap.parse_args()

    targets = []
    if a.root:
        found = {s: [(lb, p) for lb, p in default_dirs(a.root, s) if os.path.isdir(p)]
                 for s in SYSTEMS}
        present = [s for s in SYSTEMS if found[s]]
        if a.system:
            system = a.system
        elif len(present) == 1:
            system = present[0]
        elif not present:
            print('標準構成のフォルダ（datasets/<系統>/sdtm/json・adam/json）が '
                  f'{a.root} に見つかりません。--dir で指定してください。')
            return 2
        else:
            print('datasets/ に系統が2つあります（' + '・'.join(present) + '）。'
                  '共有先が受け取る正本の系統を --system で指定してください。')
            return 2
        if not found[system]:
            print(f'datasets/{system}/sdtm/json・adam/json が {a.root} に見つかりません。')
            return 2
        targets.extend(found[system])
        print(f'系統: {system}')
    for spec in a.dir + a.file:
        if '=' not in spec:
            print(f'--dir / --file は ラベル=パス の形で指定してください: {spec}')
            return 2
        label, path = spec.split('=', 1)
        targets.append((label, path))
    if not targets:
        print('--root か --dir / --file のいずれかを指定してください。')
        return 2

    allow = set(a.allow)
    cells = []
    for label, path in targets:
        print(f'検査 : {label}  {path}')
        cells += scan_target(label, path)

    byvar = Counter(f'{d}.{v}' for _, d, v, _ in cells)
    if not byvar:
        print('\n非 ASCII の値はありません。')
        return 0

    bad = 0
    if not a.chars_only:
        print(f'\n非 ASCII を含むセル : {len(cells)}')
        for key, n in sorted(byvar.items(), key=lambda x: (-x[1], x[0])):
            allowed = key in allow
            if not allowed:
                bad += n
            print(f'  {key:18} {n:6} セル  {"許容" if allowed else "方針外"}')
            vals = sorted({v for _, d, vr, v in cells if f'{d}.{vr}' == key})
            for s in vals[:a.max_cells]:
                print(f'{"":20}{s if len(s) <= 100 else s[:100] + chr(8230)}')
            if len(vals) > a.max_cells:
                print(f'{"":20}... 他 {len(vals) - a.max_cells} 種')
    else:
        bad = sum(n for k, n in byvar.items() if k not in allow)

    # CP932 にはあるが JIS X 0208 には無い文字。Shift_JIS を厳密に実装した処理系で
    # 別の文字になる。代表は U+FF5E（全角チルダ）と U+FF0D（全角ハイフンマイナス）で、
    # CP932 は 0x8160・0x817C をこの2文字に、JIS X 0208 側の実装は U+301C（波ダッシュ）・
    # U+2212（マイナス記号）に対応させる。
    chars = Counter(ch for _, _, _, v in cells for ch in v if ord(ch) not in ASCII_OK)
    risky = [ch for ch in chars if encodable(ch, 'cp932') and not encodable(ch, 'shift_jis')]
    nocp = [ch for ch in chars if not encodable(ch, 'cp932')]
    print(f'\n非 ASCII の文字種 : {len(chars)}')
    print(f'CP932 で表せない文字 : {len(nocp)}')
    for ch in sorted(nocp):
        print(f'  U+{ord(ch):04X} {ch}  {chars[ch]:5} 回  {unicodedata.name(ch, "?")}')
    print(f'CP932 にはあるが JIS X 0208 には無い文字 : {len(risky)}')
    for ch in sorted(risky, key=lambda c: -chars[c]):
        where = sorted({f'{d}.{v}' for _, d, v, s in cells if ch in s})
        print(f'  U+{ord(ch):04X} {ch}  {chars[ch]:5} 回  '
              f'{unicodedata.name(ch, "?")}  {", ".join(where)}')

    print(f'\n許容していない非 ASCII のセル : {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
