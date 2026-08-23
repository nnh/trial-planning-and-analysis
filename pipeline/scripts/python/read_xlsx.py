# read_xlsx.py
#
# xlsx を読む。標準ライブラリだけで動く。
#
#   python read_xlsx.py <file.xlsx>                    全シートを人が読む形で
#   python read_xlsx.py <file.xlsx> --list             シート名と行数だけ
#   python read_xlsx.py <file.xlsx> --sheet <名前>      1シートだけ
#   python read_xlsx.py <file.xlsx> --csv --sheet <名前> CSV で標準出力へ
#   python read_xlsx.py <file.xlsx> --max-rows 200     出す行数の上限（既定 50、0 で無制限）
#
# シート名がハイフンで始まるときは = でつなぐ（--sheet=--SPID）。空白で区切ると
# argparse がオプション名と読む。Ptosh の受領資料には --SPID というシートが実在する。
#
# モジュールとしても使う。
#
#   from read_xlsx import sheet_names, read_sheet
#   for row in read_sheet('資料.xlsx', '仕様'):
#       ...   # row は文字列のリスト
#
# なぜ openpyxl を使わないか。この枠組みの Python は全スクリプトが標準ライブラリだけで
# 動く。受領資料の xlsx を読むためだけに外部パッケージを足すと、端末ごとに導入と版の管理が
# 生まれる。対象の端末には pip が通らないものがあり（企業ネットワークの制約）、導入できた
# 端末とできない端末で同じスクリプトが動かなくなる。読むだけなら xlsx は ZIP と XML なので
# 標準ライブラリで足りる。書き出しは R 側（openxlsx2）が持つので、ここでは読み取りに限る。
#
# 扱わないもの。数式の再計算（保存時の値を返す）、書式（色・罫線）、グラフ、ピボット、
# 結合セル（左上のセルにだけ値が入り、他は空で返る）。受領資料を読む用途では足りている。

import argparse
import csv
import datetime
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

MAIN = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
RELS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'

# 日付・時刻の組み込み書式 ID（ECMA-376 の既定）。これに当たる numFmt を持つセルは
# シリアル値を日付へ直す。14-22 が日付と時刻、45-47 が経過時間。
BUILTIN_DATE_IDS = set(range(14, 23)) | {45, 46, 47}
DATE_TOKENS = re.compile(r'(?<!\\)[dmyhs]', re.IGNORECASE)
EPOCH = datetime.datetime(1899, 12, 30)   # Excel のシリアル値 1 = 1900-01-01


def _shared_strings(z):
    if 'xl/sharedStrings.xml' not in z.namelist():
        return []
    root = ET.fromstring(z.read('xl/sharedStrings.xml'))
    return [''.join(t.text or '' for t in si.iter(MAIN + 't')) for si in root]


def _date_styles(z):
    """日付として表示されるセルスタイルの番号（cellXfs のインデックス）"""
    if 'xl/styles.xml' not in z.namelist():
        return set()
    root = ET.fromstring(z.read('xl/styles.xml'))
    custom = {}
    for nf in root.iter(MAIN + 'numFmt'):
        code = nf.get('formatCode') or ''
        # 文字列リテラルを外してから d/m/y/h/s を探す。"0.00" 等は日付ではない
        stripped = re.sub(r'"[^"]*"', '', code)
        if DATE_TOKENS.search(stripped):
            custom[int(nf.get('numFmtId'))] = True
    out = set()
    xfs = root.find(MAIN + 'cellXfs')
    if xfs is None:
        return out
    for i, xf in enumerate(xfs):
        fid = int(xf.get('numFmtId') or 0)
        if fid in BUILTIN_DATE_IDS or custom.get(fid):
            out.add(i)
    return out


def _sheet_targets(z):
    """[(シート名, ZIP 内のパス), ...] を並び順で返す"""
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    rels = {r.get('Id'): r.get('Target')
            for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
    out = []
    for sh in wb.find(MAIN + 'sheets'):
        target = (rels.get(sh.get(RELS + 'id')) or '').lstrip('/')
        if target and not target.startswith('xl/'):
            target = 'xl/' + target
        out.append((sh.get('name'), target))
    return out


def _col_index(ref):
    """セル参照 'AB12' から 0 始まりの列番号"""
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def _cell_value(c, shared, date_styles):
    t = c.get('t')
    if t == 'inlineStr':
        el = c.find(MAIN + 'is')
        return ''.join(x.text or '' for x in el.iter(MAIN + 't')) if el is not None else ''
    v = c.find(MAIN + 'v')
    if v is None or v.text is None:
        return ''
    if t == 's':
        i = int(v.text)
        return shared[i] if i < len(shared) else ''
    if t == 'e':          # エラー値（#REF! など）はそのまま返す
        return v.text
    if t == 'b':
        return 'TRUE' if v.text == '1' else 'FALSE'
    s = c.get('s')
    if s is not None and int(s) in date_styles:
        try:
            f = float(v.text)
        except ValueError:
            return v.text
        d = EPOCH + datetime.timedelta(days=f)
        # 時刻を持たないものは日付だけにする
        return d.strftime('%Y-%m-%d') if d.time() == datetime.time(0, 0) else d.strftime('%Y-%m-%d %H:%M:%S')
    return v.text


def sheet_names(path):
    with zipfile.ZipFile(path) as z:
        return [n for n, _ in _sheet_targets(z)]


def read_sheet(path, name=None, index=None):
    """1シートを行ごとに返す（各行は文字列のリスト）。空行も返す。

    name も index も無いときは最初のシート。行の長さはその行の最右のセルまでで、
    行によって変わる。表として使うときは呼ぶ側でそろえる。
    """
    with zipfile.ZipFile(path) as z:
        targets = _sheet_targets(z)
        if name is not None:
            hit = [t for n, t in targets if n == name]
            if not hit:
                raise KeyError(f'シートが無い: {name}（ある: {", ".join(n for n, _ in targets)}）')
            target = hit[0]
        else:
            target = targets[index or 0][1]
        shared, styles = _shared_strings(z), _date_styles(z)
        root = ET.fromstring(z.read(target))
        for row in root.iter(MAIN + 'row'):
            cells = list(row)
            if not cells:
                yield []
                continue
            width = max(_col_index(c.get('r') or 'A1') for c in cells) + 1
            out = [''] * width
            for c in cells:
                out[_col_index(c.get('r') or 'A1')] = _cell_value(c, shared, styles)
            yield out


def main():
    ap = argparse.ArgumentParser(description='xlsx を標準ライブラリだけで読む')
    ap.add_argument('path')
    ap.add_argument('--list', action='store_true', help='シート名と行数だけ出す')
    ap.add_argument('--sheet', help='読むシート名')
    ap.add_argument('--csv', action='store_true', help='CSV で標準出力へ')
    ap.add_argument('--max-rows', type=int, default=50, help='出す行数の上限（0 で無制限）')
    ap.add_argument('--max-cols', type=int, default=12, help='テキスト表示で出す列数の上限')
    a = ap.parse_args()

    names = sheet_names(a.path)
    if a.list:
        for n in names:
            print(f'{n}\t{sum(1 for _ in read_sheet(a.path, n))} 行')
        return

    targets = [a.sheet] if a.sheet else names
    if a.csv:
        if len(targets) > 1:
            sys.exit('--csv は 1 シートだけを対象にする。--sheet で指定する。')
        w = csv.writer(sys.stdout)
        for i, row in enumerate(read_sheet(a.path, targets[0])):
            if a.max_rows and i >= a.max_rows:
                break
            w.writerow(row)
        return

    for n in targets:
        print(f'===== {n} =====')
        for i, row in enumerate(read_sheet(a.path, n)):
            if a.max_rows and i >= a.max_rows:
                print('  …（以降省略。--max-rows 0 で全部）')
                break
            line = ' | '.join(x.strip() for x in row[:a.max_cols]).strip(' |')
            if line:
                print('  ' + line)


if __name__ == '__main__':
    main()
