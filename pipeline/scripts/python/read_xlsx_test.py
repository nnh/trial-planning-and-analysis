# read_xlsx_test.py
#
#   python read_xlsx_test.py
#
# read_xlsx.py の回帰確認。最小の xlsx をその場で組み立てて読み、日付の変換・数値の
# 非変換・列の飛びを確かめる。標準ライブラリだけで動き、外部の xlsx を要らない。
#
# 日付の期待値は Excel の 1900 日付システムで広く知られた対応（シリアル値 44927 =
# 2023-01-01）を使う。read_xlsx と同じ計算で期待値を作ると検証にならないため、
# 定数で置いている。

import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from read_xlsx import read_sheet, sheet_names   # noqa: E402

CONTENT_TYPES = '''<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>'''

ROOT_RELS = '''<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'''

WORKBOOK = '''<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="--SPID" sheetId="1" r:id="rId1"/></sheets></workbook>'''

WORKBOOK_RELS = '''<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'''

# スタイル 0=既定 / 1=組み込みの日付(14) / 2=カスタムの日時 / 3=小数2桁(2)
STYLES = '''<?xml version="1.0"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="180" formatCode="yyyy&quot;年&quot;m&quot;月&quot;d&quot;日&quot; h:mm"/></numFmts>
<cellXfs count="4"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="180"/><xf numFmtId="2"/></cellXfs></styleSheet>'''

SHEET = '''<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
<row r="1"><c r="A1" s="1"><v>44927</v></c><c r="B1" s="2"><v>44927.5</v></c><c r="C1" s="3"><v>3.14</v></c>
<c r="D1" s="0"><v>42</v></c><c r="F1" t="inlineStr"><is><t>飛んだ列</t></is></c></row>
<row r="2"><c r="A2" t="b"><v>1</v></c><c r="B2" t="e"><v>#REF!</v></c></row></sheetData></worksheet>'''


def build(path):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('[Content_Types].xml', CONTENT_TYPES)
        z.writestr('_rels/.rels', ROOT_RELS)
        z.writestr('xl/workbook.xml', WORKBOOK)
        z.writestr('xl/_rels/workbook.xml.rels', WORKBOOK_RELS)
        z.writestr('xl/styles.xml', STYLES)
        z.writestr('xl/worksheets/sheet1.xml', SHEET)


def main():
    path = os.path.join(tempfile.mkdtemp(), 'fixture.xlsx')
    build(path)

    assert sheet_names(path) == ['--SPID'], sheet_names(path)

    rows = list(read_sheet(path))
    first, second = rows[0], rows[1]

    assert first[0] == '2023-01-01', f'組み込みの日付書式: {first[0]}'
    assert first[1] == '2023-01-01 12:00:00', f'カスタムの日時書式: {first[1]}'
    assert first[2] == '3.14', f'小数の書式を日付にしない: {first[2]}'
    assert first[3] == '42', f'既定の書式: {first[3]}'
    assert first[4] == '' and first[5] == '飛んだ列', f'飛んだ列の詰まり: {first}'
    assert second[0] == 'TRUE', f'真偽値: {second[0]}'
    assert second[1] == '#REF!', f'エラー値はそのまま返す: {second[1]}'

    # シート名でも読める（ハイフン始まりのシート名）
    assert list(read_sheet(path, '--SPID'))[0][3] == '42'

    try:
        list(read_sheet(path, '無い名前'))
    except KeyError:
        pass
    else:
        raise AssertionError('無いシート名は KeyError にする')

    print('read_xlsx: 8 件すべて合格')


if __name__ == '__main__':
    main()
