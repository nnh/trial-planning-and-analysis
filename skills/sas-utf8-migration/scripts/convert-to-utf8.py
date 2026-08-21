# convert-to-utf8.py
#
# CP932 のテキストファイルを UTF-8（BOM なし）へ変換する。
# 変換したものを CP932 へ戻して元のバイト列と一致するものだけを書き換える。
# 一致しないものは変換せずに報告するので、中身を見てから個別に決める。
#
#   python convert-to-utf8.py <ルート> --dry-run
#   python convert-to-utf8.py <ルート>
#   python convert-to-utf8.py <ルート> --ext sas
#   python convert-to-utf8.py <ファイル> --backup-dir <控えの置き場>
#
# 受領データを変換するときは --backup-dir で原本の控えを取る。
import sys, os, io, shutil, argparse

DEFAULT_EXT = 'sas,csv,txt,r,py,md,ps1'
SKIP_DIR = {'.git', '__pycache__', 'node_modules', '.venv', 'renv'}


def is_cp932_only(b):
    """CP932 としてしか読めない（＝変換が要る）かを見る"""
    try:
        b.decode('ascii')
        return False
    except UnicodeDecodeError:
        pass
    try:
        b.decode('utf-8')
        return False          # 既に UTF-8
    except UnicodeDecodeError:
        pass
    try:
        b.decode('cp932')
        return True
    except UnicodeDecodeError:
        return False          # どちらでもない


def collect(root, exts):
    if os.path.isfile(root):
        return [root]
    out = []
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR]
        for f in files:
            if os.path.splitext(f)[1].lower() in exts:
                out.append(os.path.join(dirpath, f))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('root')
    ap.add_argument('--ext', default=DEFAULT_EXT)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--backup-dir', help='変換前の控えを置く場所')
    a = ap.parse_args()
    exts = {('.' + e.strip().lstrip('.')).lower() for e in a.ext.split(',')}

    targets, skipped = [], []
    for p in collect(a.root, exts):
        b = io.open(p, 'rb').read()
        if not is_cp932_only(b):
            continue
        try:
            u = b.decode('cp932').encode('utf-8')
        except UnicodeDecodeError as e:
            skipped.append((p, f'CP932 として読めない: {e}'))
            continue
        if u.decode('utf-8').encode('cp932') != b:
            skipped.append((p, '戻したとき元と一致しない（CP932 に無い文字か、往復で変わる文字がある）'))
            continue
        targets.append((p, b, u))

    print(f'変換の対象 {len(targets)} 件 / 見送り {len(skipped)} 件')
    for p, why in skipped:
        print(f'  見送り: {p}\n          {why}')
    for p, b, u in targets:
        print(f'  {len(b):>9,} -> {len(u):>9,}  {p}')

    if a.dry_run:
        print('\n--dry-run のため書き換えていない')
        return 0

    if a.backup_dir and targets:
        os.makedirs(a.backup_dir, exist_ok=True)
    for p, b, u in targets:
        if a.backup_dir:
            shutil.copy2(p, os.path.join(a.backup_dir, os.path.basename(p)))
        io.open(p, 'wb').write(u)

    # 書いたものが BOM なし UTF-8 として読めることを確かめる
    ng = []
    for p, _, _ in targets:
        b = io.open(p, 'rb').read()
        if b.startswith(b'\xef\xbb\xbf'):
            ng.append((p, 'BOM が付いている'))
            continue
        try:
            b.decode('utf-8')
        except UnicodeDecodeError:
            ng.append((p, 'UTF-8 として読めない'))
    if ng:
        for p, why in ng:
            print(f'  検査で落ちた: {p}（{why}）')
        return 1
    print(f'\n{len(targets)} 件を UTF-8（BOM なし）へ変換した'
          + (f'。控え: {a.backup_dir}' if a.backup_dir else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
