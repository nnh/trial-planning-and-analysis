# scan-encoding.py
#
# 指定したルートの下にあるテキストファイルの文字符号化を調べ、混在を報告する。
# SAS を UTF-8 セッションへ移す前に、ソースと入力データの両方にかける。
# CP932 の CSV が1つ混ざっていると proc import が列をずらすため、入力データを外さない。
#
#   python scan-encoding.py <ルート> [<ルート2> ...]
#   python scan-encoding.py <ルート> --ext sas,csv,txt
#   python scan-encoding.py <ルート> --only cp932     ... CP932 のものだけ出す
import sys, os, io, argparse, collections

DEFAULT_EXT = 'sas,csv,txt,r,py,md,ps1,json,xml'
SKIP_DIR = {'.git', '__pycache__', 'node_modules', '.venv', 'renv'}


def sniff(path):
    b = io.open(path, 'rb').read()
    if b.startswith(b'\xef\xbb\xbf'):
        return 'UTF-8-BOM', len(b)
    try:
        b.decode('ascii')
        return 'ASCII', len(b)
    except UnicodeDecodeError:
        pass
    try:
        b.decode('utf-8')
        return 'UTF-8', len(b)
    except UnicodeDecodeError:
        pass
    try:
        b.decode('cp932')
        return 'CP932', len(b)
    except UnicodeDecodeError:
        return 'UNKNOWN', len(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('roots', nargs='+')
    ap.add_argument('--ext', default=DEFAULT_EXT, help='対象の拡張子（カンマ区切り）')
    ap.add_argument('--only', help='この符号化のものだけ出す（cp932 等）')
    a = ap.parse_args()
    exts = {('.' + e.strip().lstrip('.')).lower() for e in a.ext.split(',')}

    rows = []
    for root in a.roots:
        if not os.path.exists(root):
            print(f'見つかりません: {root}')
            continue
        for dirpath, dirnames, files in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR]
            for f in files:
                if os.path.splitext(f)[1].lower() not in exts:
                    continue
                p = os.path.join(dirpath, f)
                try:
                    enc, size = sniff(p)
                except OSError as e:
                    print(f'読めません: {p}（{e}）')
                    continue
                rows.append((enc, size, p))

    by = collections.defaultdict(list)
    for enc, size, p in rows:
        by[enc].append((size, p))

    print(f'見たファイル {len(rows)} 件')
    for enc in sorted(by):
        if a.only and enc.lower() != a.only.lower():
            continue
        print(f'\n{enc}: {len(by[enc])} 件')
        for size, p in sorted(by[enc], key=lambda x: x[1]):
            print(f'  {size:>10,}  {p}')

    cp932 = len(by.get('CP932', []))
    unknown = len(by.get('UNKNOWN', []))
    # BOM は SAS のソースでだけ問題になる。レビュー用の CSV は Excel がそのまま開けるよう
    # BOM を付けることがあるので、拡張子を見てから言う
    bom_sas = [p for _, p in by.get('UTF-8-BOM', []) if p.lower().endswith('.sas')]
    print()
    if cp932:
        print(f'CP932 が {cp932} 件ある。UTF-8 セッションへ移すなら convert-to-utf8.py にかける')
    if bom_sas:
        print(f'BOM 付きの .sas が {len(bom_sas)} 件ある。SAS は BOM 付きのソースを読めないので落とす')
        for q in bom_sas:
            print(f'  {q}')
    bom = len(bom_sas)
    if unknown:
        print(f'判定できないものが {unknown} 件ある。中身を見る')
    if not (cp932 or bom or unknown):
        print('混在なし')
    return 1 if (cp932 or unknown) else 0


if __name__ == '__main__':
    sys.exit(main())
