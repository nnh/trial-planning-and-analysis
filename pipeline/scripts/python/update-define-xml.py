# update-define-xml.py
#
# データセンターから受領した define.xml（Define-XML 2.0.0 / SDTM-IG 3.2）に、
# SDTM 層で足した変数とドメインを反映した define.xml を作る。
#
# 入力は受領 define.xml と docs/metadata/ の宣言だけで、実装系統（SAS・R）の作った
# データセットを読まない。define は試験に1組で系統を持たないので、中立のコードが中立の
# 宣言を読んで中立の場所へ書く（2026-09-05、段F。
# docs/records/sas-to-r-package-migration-20260905.md）。
#
# 入力  : 受領 define.xml（Box の固定データ内。読み取りのみ）
#         docs/metadata/variable-map.csv          変数の集合・ラベル・宣言長
#         docs/metadata/external/sdtm_variable_order.csv   標準の変数順
#         docs/metadata/sdtm-value-level.csv      --TESTCD から --TEST
#         docs/metadata/sdtm-codelist-values.csv  CodeList に載せる値
#         docs/metadata/sdtm-codelist-mode.csv    CodeList の合わせ方（replace・add）と対象
#                                                 （testcd 列を入れると値水準を指す）
#         docs/metadata/codelist-decode.csv       Decode の対応
#         docs/metadata/trial-design/tv.csv       VISITNUM の Decode
#         docs/metadata/external/sdtmig-3-2-variable-roles.csv   Role と IG のラベル
#         docs/metadata/external/ct-domain-ccode.csv             DOMAIN の NCI コード
# 出力  : Box datasets/define/sdtm/define.xml、同 define2-0-0.xsl
#
# 役割分担：ラベル・宣言長・itemOID の正本は docs/metadata/variable-map.csv、
#           データセットのラベルの正本は docs/metadata/sdtm_datasets.csv
#           （docs/spec/sdtm-spec.md §2.1・§2.2.2・§2.2.3）。
#           Origin・CodeList の CRF 由来の値・値水準の骨格は受領 define.xml が正本。
#
# 宣言と実データが合っているかはここでは見ない。見るのは
# scripts/check-sdtm-declarations.py で、宣言に無い値が実データに出たら止める。
#
# 使い方  : python scripts/update-define-xml.py
#           python scripts/update-define-xml.py --out-dir <dir>   ... 書き出し先
#           python scripts/update-define-xml.py --compare <xml>   ... 作ったものと突き合わせる
#
# 納品パッケージの中でも動く。受領 define.xml は reproduce/input/rawdata/ の下に受領時の
# 階層のまま同梱してあり、宣言は reproduce/docs/metadata/ にある。Box は要らない。
import argparse
import csv
import os
import re
import shutil
import sys
import datetime
import glob
from xml.dom import expatbuilder, Node

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath

sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 受領 define.xml の置き場は docs/metadata/trial.json が持つ（受領物の根からの相対）。
# 納品パッケージでも同じ階層で同梱するので、パッケージの中と外で同じ相対パスになる。
SRC_REL = boxpath.received_define_rel()

# 受領 define.xml の名前空間。要素名は接頭辞つきの文字列としてそのまま扱う（受領物の
# 接頭辞を書き換えないため）。
NS_DEF = 'def:'


# --- .NET の XmlTextWriter と同じ整形で書き出す -------------------------------------------
# 2026-09-05 まで生成は PowerShell（update-define-xml.ps1）で、保存は .NET の
# XmlDocument.Save が行っていた。移植の前後で define.xml が1バイトも変わらないことを
# 合格条件にしたので、整形もそれに合わせる。規則は次の4つ。
#   - 改行は CRLF、字下げは2文字の空白
#   - 子を持たない要素は、作った要素なら <x />、受領物にあった <x></x> はそのまま
#   - 文字列を子に持つ要素は字下げせず1行に収める
#   - 本文中の改行は原文のまま（LF）残す
def esc_text(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def esc_attr(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace(chr(13), '&#xD;').replace(chr(10), '&#xA;').replace(chr(9), '&#x9;'))


def _write_element(el, depth, out):
    out.append('<' + el.tagName)
    for name, value in el.attributes.items():
        out.append(' %s="%s"' % (name, esc_attr(value)))
    kids = [c for c in el.childNodes
            if c.nodeType in (Node.ELEMENT_NODE, Node.TEXT_NODE, Node.CDATA_SECTION_NODE)]
    if not kids:
        # 作った要素は空要素タグ、受領物にあった <x></x> は開始と終了を分けて書く
        if getattr(el, 'net_empty', False):
            out.append(' />')
        else:
            out.append('>' + CRLF + '  ' * depth + '</' + el.tagName + '>')
        return
    out.append('>')
    texts = [c for c in kids if c.nodeType != Node.ELEMENT_NODE]
    if texts:
        if any(c.nodeType == Node.ELEMENT_NODE for c in kids):
            raise SystemExit('文字列と要素が混ざった子を持つ要素があります: ' + el.tagName)
        for c in kids:
            out.append(esc_text(c.data))
        out.append('</' + el.tagName + '>')
        return
    for c in kids:
        out.append(CRLF + '  ' * (depth + 1))
        _write_element(c, depth + 1, out)
    out.append(CRLF + '  ' * depth + '</' + el.tagName + '>')


CRLF = chr(13) + chr(10)


def serialize(doc):
    out = []
    for node in doc.childNodes:
        if node.nodeType == Node.PROCESSING_INSTRUCTION_NODE:
            out.append('<?%s %s?>%s' % (node.target, node.data, CRLF))
        elif node.nodeType == Node.COMMENT_NODE:
            out.append('<!--%s-->%s' % (node.data, CRLF))
        elif node.nodeType == Node.ELEMENT_NODE:
            _write_element(node, 0, out)
    return ''.join(out)


def strip_space(el):
    """空白だけの文字列ノードを落とす（.NET の PreserveWhitespace=false と同じ扱い）。"""
    for c in list(el.childNodes):
        if c.nodeType == Node.TEXT_NODE and not c.data.strip():
            el.removeChild(c)
        elif c.nodeType == Node.ELEMENT_NODE:
            strip_space(c)


# --- DOM の小さな道具 ---------------------------------------------------------------------
def kids(el, tag):
    """直下の子要素のうち名前が一致するもの（接頭辞を含めて比べる）"""
    return [c for c in el.childNodes
            if c.nodeType == Node.ELEMENT_NODE and c.tagName == tag]


def kid(el, tag):
    got = kids(el, tag)
    return got[0] if got else None


def descendants(el, tag):
    out = []
    for c in el.childNodes:
        if c.nodeType != Node.ELEMENT_NODE:
            continue
        if c.tagName == tag:
            out.append(c)
        out += descendants(c, tag)
    return out


def text_of(el):
    return ''.join(c.data for c in el.childNodes if c.nodeType == Node.TEXT_NODE)


def set_text(el, s):
    for c in list(el.childNodes):
        el.removeChild(c)
    el.appendChild(el.ownerDocument.createTextNode(s))
    el.net_empty = False


def make(doc, tag, **attrs):
    el = doc.createElement(tag)
    el.net_empty = True
    for k, v in attrs.items():
        el.setAttribute(k.replace('__', ':'), v)
    return el


def append(parent, child):
    parent.appendChild(child)
    parent.net_empty = False
    return child


def insert_after(parent, node, ref):
    nxt = ref.nextSibling
    if nxt is None:
        parent.appendChild(node)
    else:
        parent.insertBefore(node, nxt)
    parent.net_empty = False
    return node


def clone(el):
    """net_empty も含めて深く写す"""
    new = el.ownerDocument.createElement(el.tagName)
    new.net_empty = getattr(el, 'net_empty', False)
    for name, value in el.attributes.items():
        new.setAttribute(name, value)
    for c in el.childNodes:
        if c.nodeType == Node.ELEMENT_NODE:
            new.appendChild(clone(c))
        elif c.nodeType == Node.TEXT_NODE:
            new.appendChild(el.ownerDocument.createTextNode(c.data))
    return new


def translated(doc, s):
    """<Description><TranslatedText xml:lang="en">s</TranslatedText></Description>"""
    de = make(doc, 'Description')
    tt = make(doc, 'TranslatedText')
    tt.setAttribute('xml:lang', 'en')
    set_text(tt, s)
    append(de, tt)
    return de


def read_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def collate(values):
    """CodeList の値の並び。大文字小文字を区別せずに並べ、同じなら元の文字列で決める。

    2026-09-05 まで PowerShell の Sort-Object が並べていた。あれは実行環境のカルチャに
    従うので、同じ入力でも端末で並びが変わり得る。ここで規則を明示して環境から切る。
    """
    return sorted(set(values), key=lambda s: (s.lower(), s))


# --- IG に無い変数のラベル ----------------------------------------------------------------
# 変数ラベルの正本は SDTM IG（docs/metadata/external/sdtmig-3-2-variable-roles.csv）。ここに
# 置くのは IG の一覧に載らない変数だけにする。IG の値を写すと、ドメインで違うラベル
# （--STRESC など）を取り違えるうえ、Library の版が変わったときにずれる。
# CO は本試験では作らない（AE 由来の全行を PV データへ出したため）が、他の試験で
# 使うことがあるので残す。
EXTRA_LABEL = {
    'RDOMAIN': 'Related Domain Abbreviation',
    'COSEQ': 'Sequence Number',
    'COSPID': 'Sponsor-Defined Identifier',
    'IDVAR': 'Identifying Variable',
    'IDVARVAL': 'Identifying Variable Value',
    'COVAL': 'Comment',
}

# 導出方法の説明（def:Origin Type="Derived" に添える）。
# 中身は試験ごとに書き換える。何をどう導出したかは受領データの作りと研究計画書で変わるため、
# 汎用化できるのは「導出変数には説明を添える」という形までで、説明そのものは移せない。
# 下は試験A の値で、新しい試験では自分の導出仕様から起こし直す。
DERIV_COMMENT = {
    'EPOCH': 'VISITNUM から割り付け、VISITNUM が無い場合は初回移植日と試験治療終了日を境に判定',
    'VISIT': 'VISITNUM に対応する来院名',
    'AGE': 'RFSTDTC と BRTHDTC から算出した満年齢',
    'RFXSTDTC': 'EC の ECSTDTC の最小値',
    'RFXENDTC': 'EC の ECENDTC（無い場合は ECSTDTC）の最大値',
    'RFPENDTC': 'DS の withdrawal（無い場合は discon）の DSSTDTC',
    'DTHDTC': 'DS の EPOCH=FOLLOW-UP かつ DSTERM=DEATH の DSSTDTC',
    'DTHFL': 'DTHDTC が非欠測のとき Y',
    'ACTARMCD': 'EC に投与記録が無い症例は SCRNFAIL、それ以外は ARMCD と同値',
    'ACTARM': 'EC に投与記録が無い症例は Screen Failure、それ以外は ARM と同値',
    'CESTDTC': 'CEDTC を移送',
    'CEDECOD': 'CETERM と同値',
    'DSDECOD': 'DSTERM と同値（試験固有の中止理由は標準用語へ丸めない）',
    'PRINDC': '外部データ engraftment.csv の RETXRSN（再移植の理由）',
    'RSBLFL': 'ベースラインの効果判定は存在しないため全件空',
    'LBSTNRLO': 'LBORNRLO を移送（単位換算しないため同値）',
    'LBSTNRHI': '受領データに上限が無いため全件欠測',
}

# 受領 define.xml に ItemGroupDef が無いドメインを新規に作るときの属性。
# Class は SDTM IG 3.2 のクラス、Structure は IG の記述に合わせる。
# Trial Design は被験者データではないので IsReferenceData を Yes にする。
NEW_DOMAIN = {
    'CO': dict(cls='RELATIONSHIP', refdata='No',
               structure='One record per comment per subject', label='Comments'),
    'TS': dict(cls='TRIAL DESIGN', refdata='Yes',
               structure='One record per trial summary parameter value',
               label='Trial Summary'),
    'TA': dict(cls='TRIAL DESIGN', refdata='Yes',
               structure='One record per planned element per arm', label='Trial Arms'),
    'TE': dict(cls='TRIAL DESIGN', refdata='Yes',
               structure='One record per planned element', label='Trial Elements'),
    'TI': dict(cls='TRIAL DESIGN', refdata='Yes',
               structure='One record per inclusion or exclusion criterion',
               label='Trial Inclusion/Exclusion Criteria'),
    'TV': dict(cls='TRIAL DESIGN', refdata='Yes',
               structure='One record per planned visit per arm', label='Trial Visits'),
}


# 数値のうち integer にするのは、定義の上で整数しか取らない変数だけ。基準範囲
# （--STNRLO・--STNRHI）は検査値と同じ尺度を持ち小数を取り得るため float とする。
# 同じ規則を R（program/r/ap_common.R の ap_datatype）と
# SAS（program/sas/<試験ID>_SDTMtoJSON.sas）が持ち、3実装の一致は
# scripts/check-datatype-rule.py が見る。
INT_NAME = re.compile(r'(SEQ|DY|TPTNUM|LLTCD|PTCD|HLTCD|HLGTCD|BDSYCD|SOCCD)$'
                      r'|^(VISITNUM|AGE|TAETORD)$')


def data_type(name, kind):
    """Define-XML の DataType。kind は char / num"""
    if kind == 'num':
        return 'integer' if INT_NAME.search(name) else 'float'
    if name.endswith('DTC'):
        return 'date'
    return 'text'


def read_variables(vmap_rows):
    """SDTM の変数を、データセットごとに並べて返す。

    集合と宣言長は docs/metadata/variable-map.csv、並びは標準の写し
    docs/metadata/external/sdtm_variable_order.csv が持つ。標準が並びを定めない
    Trial Design の5ドメインだけ variable-map の order 列が持つ（2026-09-05、段F）。
    型は宣言長の有無で決まる。文字型の変数には宣言長があり、数値型には無いという
    規則を sdtm-spec.md §2.2.2 が置いているので、別の列を作らない。
    """
    order_csv = os.path.join(REPO, 'docs', 'metadata', 'external', 'sdtm_variable_order.csv')
    if not os.path.exists(order_csv):
        raise SystemExit('標準の変数順がありません: %s' % order_csv)
    std = {}
    for r in read_csv(order_csv):
        std['%s.%s' % (r['dataset'], r['variable'])] = int(r['order'])

    by_ds = {}
    for r in vmap_rows:
        if r['layer'] != 'sdtm':
            continue
        by_ds.setdefault(r['dataset'], []).append(r)

    out = []
    for ds in sorted(by_ds):
        rows = by_ds[ds]
        in_std = ['%s.%s' % (ds, r['variable']) in std for r in rows]
        # データセット単位でどちらかに決まる。混ざると同じ並びの正本が2つになる
        if any(in_std) and not all(in_std):
            miss = [r['variable'] for r, ok in zip(rows, in_std) if not ok]
            raise SystemExit('%s: 標準の変数順に無い変数があります: %s' % (ds, '、'.join(miss)))
        if all(in_std):
            keyed = [(std['%s.%s' % (ds, r['variable'])], r) for r in rows]
        else:
            for r in rows:
                if not r['order'].strip():
                    raise SystemExit(
                        '%s.%s: 標準が並びを定めないので variable-map.csv の order が要ります'
                        % (ds, r['variable']))
            keyed = [(int(r['order']), r) for r in rows]
        if len({k for k, _ in keyed}) != len(keyed):
            raise SystemExit('%s: 並びの値が重複しています' % ds)
        vs = []
        for n, (_, r) in enumerate(sorted(keyed, key=lambda x: x[0]), 1):
            vs.append({'name': r['variable'], 'varnum': n,
                       'type': 'char' if r['length'].strip() else 'num'})
        out.append((ds, vs))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', help='define.xml の書き出し先'
                                      '（既定 Box の datasets/define/sdtm）')
    ap.add_argument('--src-dir', help='受領 define.xml のフォルダ')
    ap.add_argument('--compare', help='作った define.xml をこのファイルと突き合わせる'
                                      '（CreationDateTime を除いて比べる）')
    a = ap.parse_args()

    # Box が無い端末（納品パッケージの中）でも動かす。受領物と書き出し先が手元にあれば
    # Box は要らない。
    box = boxpath.trial_dir(required=False)
    src_dir = a.src_dir
    if not src_dir:
        for base in (REPO, box):
            if base and os.path.isdir(os.path.join(base, SRC_REL)):
                src_dir = os.path.join(base, SRC_REL)
                break
    if not src_dir:
        raise SystemExit('受領 define.xml のフォルダが見つかりません（%s）。'
                         '--src-dir で指してください。' % SRC_REL)
    # define は試験に1組で実装系統を持たないので、系統別の datasets/sas・datasets/r ではなく
    # datasets/define/<層> へ書く（2026-09-05、段E。docs/reporting/traceability-design.md
    # 「define の置き場」）
    out_dir = a.out_dir or (os.path.join(box, 'datasets', 'define', 'sdtm') if box else None)
    if not out_dir:
        raise SystemExit('書き出し先が決まりません。--out-dir で指してください。')
    os.makedirs(out_dir, exist_ok=True)

    # ---- 変数の集合・宣言長・並び ----------------------------------------------------------
    # 正本は docs/metadata/variable-map.csv（docs/spec/sdtm-spec.md §2.2.2）。実測長でも
    # SAS の宣言長でもなく、この CSV が決めた値を define.xml と Dataset-JSON の両方が書く。
    vmap_csv = os.path.join(REPO, 'docs', 'metadata', 'variable-map.csv')
    if not os.path.exists(vmap_csv):
        raise SystemExit('変数マップがありません: %s' % vmap_csv)
    vmap_rows = read_csv(vmap_csv)
    len_of = {}
    for r in vmap_rows:
        if r['layer'] != 'sdtm':
            continue
        if r['length'].strip():
            len_of['%s.%s' % (r['dataset'], r['variable'])] = int(r['length'])
    if not len_of:
        raise SystemExit('%s に layer=sdtm の宣言長がありません' % vmap_csv)
    by_dom = read_variables(vmap_rows)

    # ---- 元 define.xml を読む ------------------------------------------------------------
    cand = sorted(glob.glob(os.path.join(src_dir, 'define-*.xml')))
    if not cand:
        raise SystemExit('受領 define.xml が見つかりません: %s' % src_dir)
    src_xml = cand[0]
    print('元ファイル: %s' % src_xml)

    # 名前空間を解決しないで読む。接頭辞つきの名前をそのまま持ち、xmlns の宣言も普通の
    # 属性として原文の位置に残るので、受領物の書き方を変えずに書き戻せる
    doc = expatbuilder.parse(src_xml, namespaces=False)
    strip_space(doc.documentElement)
    odm = doc.documentElement
    mdv = kid(kid(odm, 'Study'), 'MetaDataVersion')

    def_by_oid = {d.getAttribute('OID'): d for d in kids(mdv, 'ItemDef')}

    # SDTM IG 3.2 の Role と Label。ItemRef の Role と、受領 define.xml に無い変数の
    # ラベルに使う。ラベルの正本はこの CSV で、スキル cdisc-define-xml の
    # export-sdtm-metadata.py が CDISC CORE のキャッシュ（元は CDISC Library）から作る。
    role_csv = os.path.join(REPO, 'docs', 'metadata', 'external',
                            'sdtmig-3-2-variable-roles.csv')
    if not os.path.exists(role_csv):
        raise SystemExit('変数の Role 一覧がありません: %s '
                         '（先に scripts/export-sdtmig-roles.py を実行）' % role_csv)
    role_of, ig_label_of = {}, {}
    for r in read_csv(role_csv):
        k = '%s.%s' % (r['domain'], r['variable'])
        if r['role']:
            role_of[k] = r['role']
        if r['label']:
            ig_label_of[k] = r['label']

    added = updated = new_groups = requalified = dropped = 0
    stale = []

    for dom, variables in by_dom:
        ig = None
        for g in kids(mdv, 'ItemGroupDef'):
            if g.getAttribute('Name') == dom:
                ig = g
                break

        # --- ItemGroupDef が無いドメインは新規に作る ---
        # 受領 define.xml に無いのは、SDTM 層で作ったドメイン（Trial Design）と、
        # 受領時に define へ載っていなかったドメイン。Class・Structure は SDTM IG 3.2 に従う。
        if ig is None:
            if dom not in NEW_DOMAIN:
                raise SystemExit('ItemGroupDef が無いドメイン %s の定義がありません'
                                 '（スクリプトの NEW_DOMAIN に追記してください）' % dom)
            m = NEW_DOMAIN[dom]
            ig = make(doc, 'ItemGroupDef')
            ig.setAttribute('OID', 'IG.' + dom)
            ig.setAttribute('Name', dom)
            ig.setAttribute('Domain', dom)
            ig.setAttribute('SASDatasetName', dom)
            ig.setAttribute('Repeating', 'Yes')
            ig.setAttribute('IsReferenceData', m['refdata'])
            ig.setAttribute('Purpose', 'Tabulation')
            ig.setAttribute(NS_DEF + 'Class', m['cls'])
            ig.setAttribute(NS_DEF + 'Structure', m['structure'])
            ig.setAttribute(NS_DEF + 'ArchiveLocationID', 'LF.' + dom)
            append(ig, translated(doc, m['label']))
            insert_after(mdv, ig, kids(mdv, 'ItemGroupDef')[-1])
            new_groups += 1
            print('ItemGroupDef を新規作成: %s' % dom)

        ref_by_name = {}
        for ir in kids(ig, 'ItemRef'):
            d = def_by_oid.get(ir.getAttribute('ItemOID'))
            if d is not None:
                ref_by_name[d.getAttribute('Name')] = [ir, d]

        for v in variables:
            name = v['name']
            order = v['varnum']
            dtype = data_type(name, v['type'])
            # 宣言長は変数マップが正本。文字型にだけ付ける（数値の Length は Define-XML 2.0
            # で SignificantDigits と対になる別の概念なので付けない）
            ln = len_of.get('%s.%s' % (dom, name)) if v['type'] == 'char' else None
            if v['type'] == 'char' and not ln:
                raise SystemExit('変数マップに宣言長がありません: %s.%s '
                                 '（docs/metadata/variable-map.csv）' % (dom, name))

            if name in ref_by_name:
                # --- 既存変数：順序と長さを合わせる（ラベル・Origin は元のまま） ---
                ir, d = ref_by_name[name]
                ir.setAttribute('OrderNumber', str(order))
                # itemOID は IT.<データセット>.<変数> に揃える（docs/spec/sdtm-spec.md
                # §2.2.3）。受領 define.xml は観測系15ドメインの STUDYID・USUBJID だけ
                # 修飾なしの ItemDef を ItemRef から参照し、同名の修飾形 ItemDef を孤児に
                # していた。1つの ItemDef を15のドメインが共有するため Length が1つしか
                # 書けない。受領物は読み取りのみで、張り替えるのは生成する側だけ。
                want = 'IT.%s.%s' % (dom, name)
                if d.getAttribute('OID') != want:
                    cl = clone(d)
                    cl.setAttribute('OID', want)
                    if want in def_by_oid:
                        mdv.replaceChild(cl, def_by_oid[want])
                    else:
                        insert_after(mdv, cl, kids(mdv, 'ItemDef')[-1])
                    stale.append(d.getAttribute('OID'))
                    ir.setAttribute('ItemOID', want)
                    ref_by_name[name][1] = d = cl
                    def_by_oid[want] = cl
                    requalified += 1
                if ln:
                    d.setAttribute('Length', str(ln))
                if d.getAttribute('DataType') != dtype and dtype in ('integer', 'float'):
                    d.setAttribute('DataType', dtype)
                updated += 1
                continue

            # --- 追加変数：ItemDef と ItemRef を作る ---
            # ラベルは IG が正本。ドメインで違う変数（--STRESC など）があるので
            # <ドメイン>.<変数> で引く。IG の一覧に無い変数だけ EXTRA_LABEL から補う。
            vlab = ig_label_of.get('%s.%s' % (dom, name)) or EXTRA_LABEL.get(name)
            if not vlab:
                raise SystemExit(
                    'ラベル未定義の変数があります: %s.%s'
                    '（docs/metadata/external/sdtmig-3-2-variable-roles.csv を確認するか、'
                    'スクリプトの EXTRA_LABEL に追記）' % (dom, name))
            oid = 'IT.%s.%s' % (dom, name)
            idf = make(doc, 'ItemDef')
            idf.setAttribute('OID', oid)
            idf.setAttribute('Name', name)
            idf.setAttribute('SASFieldName', name)
            idf.setAttribute('DataType', dtype)
            if ln:
                idf.setAttribute('Length', str(ln))
            append(idf, translated(doc, vlab))
            org = make(doc, NS_DEF + 'Origin')
            org.setAttribute('Type', 'Derived')
            if name in DERIV_COMMENT:
                append(org, translated(doc, DERIV_COMMENT[name]))
            append(idf, org)

            insert_after(mdv, idf, kids(mdv, 'ItemDef')[-1])
            def_by_oid[oid] = idf

            ir = make(doc, 'ItemRef')
            ir.setAttribute('ItemOID', oid)
            ir.setAttribute('OrderNumber', str(order))
            ir.setAttribute('Mandatory', 'No')
            append(ig, ir)
            added += 1

        # ArchiveLocation を Dataset-JSON のファイル名へ。
        # 受領 define.xml は xlink:href も def:title も空で、空の def:title は
        # CORE が "Missing required keyword argument _content in title" で落ちる。
        fname = dom.lower() + '.json'
        leaf = kid(ig, NS_DEF + 'leaf')
        if leaf is None:
            leaf = make(doc, NS_DEF + 'leaf')
            leaf.setAttribute('ID', 'LF.' + dom)
            append(ig, leaf)
        leaf.setAttribute('xlink:href', fname)
        title = kid(leaf, NS_DEF + 'title')
        if title is None:
            title = append(leaf, make(doc, NS_DEF + 'title'))
        set_text(title, fname)

    # 修飾形へ張り替えたことで参照が無くなった ItemDef を落とす。残すと同じ変数の ItemDef が
    # 2つ並び、どちらが生きているのか読めない。参照は ItemGroupDef と ValueListDef の両方を見る。
    referenced = {ir.getAttribute('ItemOID') for ir in descendants(mdv, 'ItemRef')}
    for oid in stale:
        if oid in referenced:
            continue
        for node in kids(mdv, 'ItemDef'):
            if node.getAttribute('OID') == oid:
                mdv.removeChild(node)
                dropped += 1
                break
    if requalified:
        print('itemOID を修飾形へ張り替え: %d 件（参照が無くなった ItemDef を %d 件落とした）'
              % (requalified, dropped))

    # def:Class を Define-XML 2.0 のコントロールドターム（大文字）に揃える。
    # 受領 define.xml は小文字（events・findings 等）で、CORE が読み込み時に
    # "Unknown value Class in ValueSet" で落ちる。
    for ig in kids(mdv, 'ItemGroupDef'):
        cls = ig.getAttribute(NS_DEF + 'Class')
        if cls and cls != cls.upper():
            ig.setAttribute(NS_DEF + 'Class', cls.upper())

    # FINDINGS ABOUT は Define-XML 2.1 で追加された値で、2.0 の値セットには無い。2.0 では
    # FINDINGS を使う（docs/validation/records/sdtm-conformance-findings-20260815.md D-1）。
    for ig in kids(mdv, 'ItemGroupDef'):
        if ig.getAttribute(NS_DEF + 'Class') == 'FINDINGS ABOUT':
            ig.setAttribute(NS_DEF + 'Class', 'FINDINGS')
            print('def:Class を FINDINGS に直した: %s' % ig.getAttribute('Name'))

    # ---- 値水準メタデータを SDTM の実データに合わせる --------------------------------------
    # 受領 define.xml は --ORRES の値水準 ItemDef の Name と SASFieldName の両方へ --TESTCD の
    # 値を入れており、Description が空になっている。SASFieldName は SAS の変数名の規則に従う
    # 必要があり、Description は値の意味を持つべきである（同 D-1）。FA は SDTM 層で FATESTCD を
    # 是正しているので、受領時の値のままの ItemDef を落とし、実データにあって define に
    # 無い値を足す（docs/spec/sdtm-spec.md 3.6）。
    # --TESTCD と --TEST の対応の正本は docs/metadata/sdtm-value-level.csv。実データから
    # 集めた値をそのまま使うのをやめ、宣言として git に置いた（2026-09-05、段F）。
    vlm_csv = os.path.join(REPO, 'docs', 'metadata', 'sdtm-value-level.csv')
    if not os.path.exists(vlm_csv):
        raise SystemExit('値水準の宣言がありません: %s' % vlm_csv)
    vlm_rows = read_csv(vlm_csv)
    test_of = {'%s.%s' % (r['domain'], r['testcd']): r['test'] for r in vlm_rows}

    oid_to_def = {d.getAttribute('OID'): d for d in kids(mdv, 'ItemDef')}
    oid_to_wc = {w.getAttribute('OID'): w for w in kids(mdv, NS_DEF + 'WhereClauseDef')}

    vl_sfn = vl_desc = vl_dropped = vl_added = vl_origin = 0

    for vl in kids(mdv, NS_DEF + 'ValueListDef'):
        # VL.FA.FAORRES から ドメインと親変数を取る
        p = vl.getAttribute('OID').split('.')
        if len(p) < 3:
            continue
        dom, var = p[1], p[2]
        parent_def = oid_to_def.get('IT.%s.%s' % (dom, var))
        seen = set()

        for ref in kids(vl, 'ItemRef'):
            it = oid_to_def.get(ref.getAttribute('ItemOID'))
            if it is None:
                continue
            q = it.getAttribute('OID').split('.')
            if len(q) < 4:
                continue
            testcd = q[3]

            if '%s.%s' % (dom, testcd) not in test_of:
                # 実データに無い --TESTCD。ItemRef・WhereClauseDef・ItemDef を落とす
                wr = kid(ref, NS_DEF + 'WhereClauseRef')
                if wr is not None:
                    w = oid_to_wc.get(wr.getAttribute('WhereClauseOID'))
                    if w is not None:
                        w.parentNode.removeChild(w)
                vl.removeChild(ref)
                it.parentNode.removeChild(it)
                vl_dropped += 1
                continue

            seen.add(testcd)
            # SASFieldName は親変数名にする（--TESTCD の値は SAS の変数名になり得ない）
            if it.getAttribute('SASFieldName') != var:
                it.setAttribute('SASFieldName', var)
                vl_sfn += 1
            # 空の Description に --TEST を入れる
            de = kid(it, 'Description')
            tt = kid(de, 'TranslatedText') if de is not None else None
            if tt is not None and not text_of(tt).strip():
                set_text(tt, test_of['%s.%s' % (dom, testcd)])
                vl_desc += 1

        # 実データにあって define に無い --TESTCD を足す
        order = len(kids(vl, 'ItemRef'))
        for r in [x for x in vlm_rows if x['domain'] == dom]:
            if r['testcd'] in seen:
                continue
            order += 1
            it_oid = 'IT.%s.%s.%s' % (dom, var, r['testcd'])
            wc_oid = 'WC.%s.%sTESTCD.%s' % (dom, dom, r['testcd'])

            nd = make(doc, 'ItemDef')
            nd.setAttribute('OID', it_oid)
            nd.setAttribute('Name', r['testcd'])
            nd.setAttribute('SASFieldName', var)
            nd.setAttribute('DataType',
                            parent_def.getAttribute('DataType') if parent_def is not None
                            else 'text')
            if parent_def is not None and parent_def.getAttribute('Length'):
                nd.setAttribute('Length', parent_def.getAttribute('Length'))
            append(nd, translated(doc, r['test']))
            # 親 ItemDef の def:Origin を丸ごと写す。値水準の項目は親変数と同じ出どころ
            # （FAORRES なら CRF）なので、def:DocumentRef・def:PDFPageRef ごと複製して既存の
            # 値水準 ItemDef と同じ形にする。親が Origin を持たないときは何も付けない。
            if parent_def is not None:
                p_org = kid(parent_def, NS_DEF + 'Origin')
                if p_org is not None:
                    append(nd, clone(p_org))
                    vl_origin += 1
            insert_after(mdv, nd, kids(mdv, 'ItemDef')[-1])
            oid_to_def[it_oid] = nd

            wd = make(doc, NS_DEF + 'WhereClauseDef')
            wd.setAttribute('OID', wc_oid)
            rc = make(doc, 'RangeCheck')
            rc.setAttribute('Comparator', 'EQ')
            rc.setAttribute('SoftHard', 'Soft')
            rc.setAttribute(NS_DEF + 'ItemOID', 'IT.%s.%sTESTCD' % (dom, dom))
            cv = make(doc, 'CheckValue')
            set_text(cv, r['testcd'])
            append(rc, cv)
            append(wd, rc)
            wcs = kids(mdv, NS_DEF + 'WhereClauseDef')
            if wcs:
                insert_after(mdv, wd, wcs[-1])
            else:
                append(mdv, wd)

            ref = make(doc, 'ItemRef')
            ref.setAttribute('ItemOID', it_oid)
            ref.setAttribute('Mandatory', 'No')
            ref.setAttribute('OrderNumber', str(order))
            wr = make(doc, NS_DEF + 'WhereClauseRef')
            wr.setAttribute('WhereClauseOID', wc_oid)
            append(ref, wr)
            append(vl, ref)
            vl_added += 1
    print('値水準メタデータ : SASFieldName %d / Description %d / 削除 %d / 追加 %d / Origin 複製 %d'
          % (vl_sfn, vl_desc, vl_dropped, vl_added, vl_origin))

    # ---- SDTM 層で値を扱った変数の CodeList を実データに合わせる ----------------------------
    # 受領 define.xml の CodeList は CRF の選択肢を写したものなので、SDTM 層で値を扱った変数
    # では実データと食い違う。扱いは mode 列が持つ。replace は実データの値だけにする（SDTM 層
    # で値体系を作り直した変数）。add は既存の値と実データの値の和にする（CRF の選択肢に SDTM
    # 層で値を足した変数。未使用の選択肢も CRF としては正しいので落とさない）。
    # どちらも専用の CodeList を作って差し替えるので、受領 define.xml が複数の変数へ同じ
    # CodeList を割り当てている場合（FATESTCD と FATEST、LBTESTCD と MBTESTCD）の共有も断てる。
    # 対象と mode の正本は docs/metadata/sdtm-codelist-mode.csv（実データからは決まらない
    # 試験固有の判断のため）。
    # 値の正本は docs/metadata/sdtm-codelist-values.csv。実データから集めた値をそのまま
    # 使うのをやめ、宣言として git に置いた（2026-09-05、段F）。粒度が違うので mode とは
    # 別の CSV にする（1つにまとめると mode が値の数だけ繰り返される）。
    mode_csv = os.path.join(REPO, 'docs', 'metadata', 'sdtm-codelist-mode.csv')
    val_csv = os.path.join(REPO, 'docs', 'metadata', 'sdtm-codelist-values.csv')
    for p in (mode_csv, val_csv):
        if not os.path.exists(p):
            raise SystemExit('CodeList の宣言がありません: %s' % p)
    # testcd 列を持つ行は値水準の CodeList を指す。1つの変数の中で --TESTCD ごとに値の
    # 体系が違うとき（FA の FAORRES は CTCAE・Glucksberg・中枢神経系白血病の3つを持つ。
    # sdtm-spec.md §3.6）に、変数単位では1つの CodeList にしか割り当てられないため。
    def cl_key(r):
        t = (r.get('testcd') or '').strip()
        return '%s.%s%s' % (r['domain'], r['variable'], '.' + t if t else '')

    mode_of = {}
    for r in read_csv(mode_csv):
        if r['mode'] not in ('replace', 'add'):
            raise SystemExit('%s: mode は replace か add: %s = "%s"'
                             % (mode_csv, cl_key(r), r['mode']))
        mode_of[cl_key(r)] = r['mode']
    cl_values = {}
    for r in read_csv(val_csv):
        key = cl_key(r)
        if key not in mode_of:
            raise SystemExit('%s に %s の行がありません（%s が値を宣言している）'
                             % (mode_csv, key, val_csv))
        cl_values.setdefault(key, []).append(r['value'])
    missing = sorted(set(mode_of) - set(cl_values))
    if missing:
        raise SystemExit('%s に値の宣言がありません: %s' % (val_csv, '、'.join(missing)))

    cl_replaced = cl_orphan = 0

    for key in sorted(cl_values):
        it = None
        for d in kids(mdv, 'ItemDef'):
            if d.getAttribute('OID') == 'IT.' + key:
                it = d
                break
        if it is None:
            print('  CodeList 同期: ItemDef が無い IT.%s （読み飛ばす）' % key)
            continue

        mode = mode_of[key]
        vals = list(cl_values[key])

        # add は既存 CodeList の値も残す（未使用の CRF 選択肢を落とさない）
        clr = kid(it, 'CodeListRef')
        if mode == 'add' and clr is not None:
            for old in kids(mdv, 'CodeList'):
                if old.getAttribute('OID') != clr.getAttribute('CodeListOID'):
                    continue
                for e in kids(old, 'EnumeratedItem') + kids(old, 'CodeListItem'):
                    vals.append(e.getAttribute('CodedValue'))
                break
        vals = collate(v for v in vals if v)
        new_oid = 'CL.' + key

        # 既に同名の CodeList があれば作り直す
        for ex in kids(mdv, 'CodeList'):
            if ex.getAttribute('OID') == new_oid:
                ex.parentNode.removeChild(ex)
                break

        cl = make(doc, 'CodeList')
        cl.setAttribute('OID', new_oid)
        cl.setAttribute('Name', key.replace('.', ' '))
        cl.setAttribute('DataType', it.getAttribute('DataType'))
        for n, v in enumerate(vals, 1):
            ei = make(doc, 'EnumeratedItem')
            ei.setAttribute('CodedValue', v)
            ei.setAttribute('OrderNumber', str(n))
            append(cl, ei)
        cls = kids(mdv, 'CodeList')
        if cls:
            insert_after(mdv, cl, cls[-1])
        else:
            append(mdv, cl)

        # ItemDef の参照を差し替える
        if clr is not None:
            clr.setAttribute('CodeListOID', new_oid)
        else:
            ref = make(doc, 'CodeListRef')
            ref.setAttribute('CodeListOID', new_oid)
            append(it, ref)
        cl_replaced += 1
        print('  CodeList 同期[%s]: %s → %s（%d 値）' % (mode, key, new_oid, len(vals)))

    # 誰からも参照されていない CodeList を消す。値水準の --TESTCD を実データに合わせて
    # 落としたときに参照が切れた CodeList と、受領 define.xml の時点でどの ItemDef からも
    # 参照されていない CodeList の両方が対象になる。受領 define.xml 自体は読み取り専用
    # なので、削除はこの出力側だけに効く。
    cl_used = {r.getAttribute('CodeListOID') for r in descendants(mdv, 'CodeListRef')}
    orphan_oids = []
    for cl in kids(mdv, 'CodeList'):
        oid = cl.getAttribute('OID')
        if oid in cl_used:
            continue
        orphan_oids.append(oid)
        cl.parentNode.removeChild(cl)
        cl_orphan += 1
        print('  参照されていない CodeList を削除: %s' % oid)
    print('CodeList : 差し替え %d / 孤立を削除 %d' % (cl_replaced, cl_orphan))
    if cl_orphan:
        print('  削除した OID: %s' % ', '.join(sorted(orphan_oids)))

    # DSCAT のコードリストに OTHER EVENT を足す。SDTM 層が DSSPID='tki_change1' の21件を
    # OTHER EVENT へ置き換えるが、受領 define.xml のコードリストは DISPOSITION EVENT の
    # 1値しか持たない（sdtm-conformance-findings-20260815.md A-2）。
    dscat_def = None
    for d in kids(mdv, 'ItemDef'):
        if d.getAttribute('Name') == 'DSCAT':
            dscat_def = d
            break
    if dscat_def is not None and kid(dscat_def, 'CodeListRef') is not None:
        cl_oid = kid(dscat_def, 'CodeListRef').getAttribute('CodeListOID')
        cl = None
        for c in kids(mdv, 'CodeList'):
            if c.getAttribute('OID') == cl_oid:
                cl = c
                break
        if cl is None:
            raise SystemExit('DSCAT のコードリストが見つかりません: %s' % cl_oid)
        items = kids(cl, 'EnumeratedItem')
        if not any(e.getAttribute('CodedValue') == 'OTHER EVENT' for e in items):
            ei = make(doc, 'EnumeratedItem')
            ei.setAttribute('CodedValue', 'OTHER EVENT')
            ei.setAttribute('OrderNumber', str(len(items) + 1))
            append(cl, ei)
            print('DSCAT のコードリスト %s に OTHER EVENT を追加しました' % cl_oid)

    # ---- CodeList に Decode を載せる --------------------------------------------------------
    # 値が略号やコードで意味が別にある CodeList を CodeListItem + Decode にする。値そのものが
    # 英語の名称になっている CodeList（FAOBJ・Microorganism・--TEST など）は EnumeratedItem の
    # ままにする。Decode を付けても同じ文字列の重複になるため。Define-XML 2.0 は1つの
    # CodeList に EnumeratedItem と CodeListItem を混在できないので、対象の CodeList は
    # 全項目を CodeListItem に置き換える。
    # Decode の正本は docs/metadata/codelist-decode.csv。受領 define.xml が値・CodeListRef の
    # 割り当ての正本である一方、英語の Decode はどこにも無いので、その差分だけを CSV に持つ
    # （docs/reporting/traceability-design.md の決定事項）。スクリプトは処理だけを持つ。
    # --TESTCD の Decode は CSV に写さない。対応する --TEST は値水準の宣言から来るため、
    # 宣言が変われば Decode も変わる。CSV に写すと二重持ちになってズレる。
    # 対応が無い値には Decode を作らない。値と同一の Decode は情報を持たないため。ただし
    # 混在できない制約から、全値の Decode がそろわない CodeList は EnumeratedItem のまま残す。
    dec_csv = os.path.join(REPO, 'docs', 'metadata', 'codelist-decode.csv')
    if not os.path.exists(dec_csv):
        raise SystemExit('Decode の対応表がありません: %s' % dec_csv)
    dec_by_cl = {}
    dec_rows = 0
    # VISITNUM の Decode は docs/metadata/trial-design/tv.csv が正本（SDTM の TV ドメインの
    # 入力そのもの）。対応表へ写すと二重持ちになり、tv.csv を直したときにズレる。ここで
    # 読んで対応表へ足す（CodeList の OID は受領 define.xml 側の CL.VA7745）。
    tv_csv = os.path.join(REPO, 'docs', 'metadata', 'trial-design', 'tv.csv')
    if os.path.exists(tv_csv):
        dec_by_cl['CL.VA7745'] = {}
        for r in read_csv(tv_csv):
            if r['visitnum'] and r['visit']:
                dec_by_cl['CL.VA7745'][r['visitnum']] = r['visit']
                dec_rows += 1
        print('VISITNUM の Decode : tv.csv から %d 件' % len(dec_by_cl['CL.VA7745']))
    else:
        print('WARNING: tv.csv がないため VISITNUM の Decode を作らない: %s' % tv_csv)
    for r in read_csv(dec_csv):
        if not r['codelist_oid']:
            continue
        dec_by_cl.setdefault(r['codelist_oid'], {})[r['coded_value']] = r['decode']
        dec_rows += 1

    # CSV と define.xml の食い違いを数えるため、define.xml 側の（CodeList OID, 値）を先に集める
    cl_val_set = set()
    for cl in kids(mdv, 'CodeList'):
        for e in kids(cl, 'EnumeratedItem') + kids(cl, 'CodeListItem'):
            cl_val_set.add((cl.getAttribute('OID'), e.getAttribute('CodedValue')))

    dc_cl = dc_item = dc_same = dc_skip_vals = 0
    dc_skip = []
    for cl in kids(mdv, 'CodeList'):
        eis = kids(cl, 'EnumeratedItem')
        if not eis:
            continue
        oid = cl.getAttribute('OID')
        ref_vars = [d.getAttribute('Name') for d in kids(mdv, 'ItemDef')
                    if kid(d, 'CodeListRef') is not None
                    and kid(d, 'CodeListRef').getAttribute('CodeListOID') == oid]
        vals = [e.getAttribute('CodedValue') for e in eis]
        cmap, src = {}, ''

        tc_var = next((v for v in ref_vars if v.endswith('TESTCD')), None)
        if tc_var:
            dom = tc_var[:-len('TESTCD')]
            for r in vlm_rows:
                if r['domain'] == dom:
                    cmap[r['testcd']] = r['test']
            src = dom + 'TEST'
        if oid in dec_by_cl:
            for k, v in dec_by_cl[oid].items():
                if not cmap.get(k):
                    cmap[k] = v
            src = (src + ' + codelist-decode.csv') if src else 'codelist-decode.csv'
        if not cmap:
            continue

        miss = [v for v in vals if not cmap.get(v)]
        if miss:
            dc_skip.append('%s[%s]' % (oid, '/'.join(sorted(miss))))
            dc_skip_vals += len(miss)
            continue

        for n, e in enumerate(eis, 1):
            dec = cmap[e.getAttribute('CodedValue')]
            if dec == e.getAttribute('CodedValue'):
                dc_same += 1
            ci = make(doc, 'CodeListItem')
            ci.setAttribute('CodedValue', e.getAttribute('CodedValue'))
            ci.setAttribute('OrderNumber', str(n))
            de = make(doc, 'Decode')
            tt = make(doc, 'TranslatedText')
            tt.setAttribute('xml:lang', 'en')
            set_text(tt, dec)
            append(de, tt)
            append(ci, de)
            cl.insertBefore(ci, e)
            dc_item += 1
        for e in eis:
            cl.removeChild(e)
        dc_cl += 1
        print('  Decode: %-22s %4d 値  (%s) ← %s'
              % (oid, len(eis), ','.join(ref_vars), src))

    # 対応表と define.xml の食い違いを報告する
    dec_no_val = 0
    for oid in dec_by_cl:
        for v in dec_by_cl[oid]:
            if (oid, v) not in cl_val_set:
                dec_no_val += 1
                print('  対応表にあって define.xml に無い値: %s の %s' % (oid, v))
    print('CodeList の Decode : %d CodeList / %d 項目（対応表 %d 行）'
          % (dc_cl, dc_item, dec_rows))
    print('  対応表にあって define.xml に無い値 %d 件 / define.xml にあって Decode の無い値 %d 件'
          % (dec_no_val, dc_skip_vals))
    if dc_skip:
        print('  Decode がそろわず EnumeratedItem のまま残した CodeList %d 件: %s'
              % (len(dc_skip), ', '.join(dc_skip)))
    if dc_same:
        print('  値と同一の Decode %d 件（--TEST の表記が --TESTCD と同じもの）' % dc_same)

    # ---- DOMAIN の CodeList を CT に合わせる --------------------------------------------------
    # CORE は DOMAIN の CodeList が持つ NCI の C コード（Alias）を CT の
    # SDTM Domain Abbreviation（C66734）と照合する（CORE-000929）。受領 define.xml は EC の
    # 項目だけ Alias が抜けており、SDTM 層で作ったドメイン（Trial Design）は CodeList を
    # 持たない。CT の写し docs/metadata/external/ct-domain-ccode.csv から補う。Decode は
    # ItemGroupDef のラベルに揃える。
    ct_csv = os.path.join(REPO, 'docs', 'metadata', 'external', 'ct-domain-ccode.csv')
    if not os.path.exists(ct_csv):
        raise SystemExit('ドメインコードの CSV がありません: %s' % ct_csv)
    dom_ccode = {r['submission_value']: r['code'] for r in read_csv(ct_csv)}

    dc_alias = dc_new_cl = 0
    for ig in kids(mdv, 'ItemGroupDef'):
        dom = ig.getAttribute('Name')
        it = None
        for d in kids(mdv, 'ItemDef'):
            if d.getAttribute('OID') == 'IT.%s.DOMAIN' % dom:
                it = d
                break
        if it is None:
            continue
        ccode = dom_ccode.get(dom)
        if not ccode:
            print('  CT に %s のドメインコードが無い（読み飛ばす）' % dom)
            continue
        de = kid(ig, 'Description')
        tt = kid(de, 'TranslatedText') if de is not None else None
        lbl = text_of(tt).strip() if tt is not None else ''
        if not lbl:
            lbl = dom

        cl_oid = 'CL.%s.DOMAIN' % dom
        cl = None
        for c in kids(mdv, 'CodeList'):
            if c.getAttribute('OID') == cl_oid:
                cl = c
                break

        if cl is not None:
            # 既にある CodeList は、その値の項目に Alias があるかを見る
            for e in kids(cl, 'CodeListItem') + kids(cl, 'EnumeratedItem'):
                if e.getAttribute('CodedValue') != dom:
                    continue
                if kids(e, 'Alias'):
                    continue
                al = make(doc, 'Alias')
                al.setAttribute('Context', 'nci:ExtCodeID')
                al.setAttribute('Name', ccode)
                append(e, al)
                dc_alias += 1
                print('  DOMAIN の Alias を追加: %s の %s → %s' % (cl_oid, dom, ccode))
            continue

        # CodeList が無いドメインは作る
        cl = make(doc, 'CodeList')
        cl.setAttribute('OID', cl_oid)
        cl.setAttribute('Name', 'SDTM Domain Abbreviation (%s)' % dom)
        cl.setAttribute('DataType', 'text')
        cl.setAttribute('SASFormatName', '$DOMAIN')
        ci = make(doc, 'CodeListItem')
        ci.setAttribute('CodedValue', dom)
        de = make(doc, 'Decode')
        tt = make(doc, 'TranslatedText')
        tt.setAttribute('xml:lang', 'en')
        set_text(tt, lbl)
        append(de, tt)
        append(ci, de)
        al = make(doc, 'Alias')
        al.setAttribute('Context', 'nci:ExtCodeID')
        al.setAttribute('Name', ccode)
        append(ci, al)
        append(cl, ci)
        alc = make(doc, 'Alias')
        alc.setAttribute('Context', 'nci:ExtCodeID')
        alc.setAttribute('Name', 'C66734')
        append(cl, alc)

        cls = kids(mdv, 'CodeList')
        if cls:
            insert_after(mdv, cl, cls[-1])
        else:
            append(mdv, cl)

        clr = kid(it, 'CodeListRef')
        if clr is not None:
            clr.setAttribute('CodeListOID', cl_oid)
        else:
            ref = make(doc, 'CodeListRef')
            ref.setAttribute('CodeListOID', cl_oid)
            append(it, ref)
        dc_new_cl += 1
        print('  DOMAIN の CodeList を作成: %s（%s / %s）' % (cl_oid, ccode, lbl))
    print('DOMAIN の CodeList : 作成 %d / Alias 補完 %d' % (dc_new_cl, dc_alias))

    # ---- ItemRef に Role を付ける -------------------------------------------------------------
    # 受領 define.xml は Role を持たず、CORE が「define-xml の role が IG と一致しない」と
    # 指摘する（CORE-001081）。SDTM IG 3.2 の Role を external/sdtmig-3-2-variable-roles.csv
    # から引いて付ける。IG に無い変数（SDTM の標準変数でないもの）には付けない。
    oid_name = {d.getAttribute('OID'): d.getAttribute('Name') for d in kids(mdv, 'ItemDef')}
    role_set = 0
    role_miss = []
    for ig in kids(mdv, 'ItemGroupDef'):
        dom = ig.getAttribute('Name')
        for ref in kids(ig, 'ItemRef'):
            nm = oid_name.get(ref.getAttribute('ItemOID'))
            if not nm:
                continue
            role = role_of.get('%s.%s' % (dom, nm))
            if not role:
                role_miss.append('%s.%s' % (dom, nm))
                continue
            if ref.getAttribute('Role') != role:
                ref.setAttribute('Role', role)
                role_set += 1
    print('ItemRef の Role : %d 件に付けた / IG に無い変数 %d 件' % (role_set, len(role_miss)))
    if role_miss:
        print('  IG に無い変数: %s' % ', '.join(sorted(set(role_miss))))

    # 作成日時と由来を更新
    odm.setAttribute('CreationDateTime',
                     datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
    odm.setAttribute('SourceSystem', '%s_CSVtoSDTM.sas' % boxpath.trial_id())

    out_xml = os.path.join(out_dir, 'define.xml')
    with open(out_xml, 'w', encoding='utf-8', newline='') as f:
        f.write(serialize(doc))
    shutil.copyfile(os.path.join(src_dir, 'define2-0-0.xsl'),
                    os.path.join(out_dir, 'define2-0-0.xsl'))

    # データセット単位の情報。正本は docs/metadata/sdtm_datasets.csv で、Dataset-JSON を
    # 書き出す側はそちらを読む（docs/spec/sdtm-spec.md §2.1）。ここでは define.xml から
    # 組み直した内容が正本と1文字も違わないことを確かめる。受領 define.xml が差し替われば
    # ここで止まるので、正本を git に置いたまま出どころとのずれを検出できる。
    ds_rows = []
    for ig in kids(mdv, 'ItemGroupDef'):
        de = kid(ig, 'Description')
        tt = kid(de, 'TranslatedText') if de is not None else None
        ds_rows.append((ig.getAttribute('Name'), text_of(tt).strip() if tt is not None else '',
                        ig.getAttribute('OID'), odm_study_oid(odm), mdv.getAttribute('OID')))
    ds_canon = os.path.join(REPO, 'docs', 'metadata', 'sdtm_datasets.csv')
    if not os.path.exists(ds_canon):
        raise SystemExit('データセットのラベルの正本がありません: %s' % ds_canon)
    canon = [(r['dataset'], r['label'], r['itemGroupOID'], r['studyOID'],
              r['metaDataVersionOID']) for r in read_csv(ds_canon)]
    if sorted(ds_rows) != sorted(canon):
        print('定義とデータセット一覧の正本が食い違っています:')
        for x in sorted(set(map(tuple, ds_rows)) ^ set(map(tuple, canon))):
            print('  ' + '\t'.join(x))
        raise SystemExit('define.xml から組んだ内容が %s と違います。'
                         'どちらが正しいかを決めてから通すこと。' % ds_canon)
    print('データセット一覧: 正本 %s と一致（%d 件）' % (ds_canon, len(canon)))

    print('')
    print('出力: %s' % out_xml)
    print('ItemGroupDef 新規 %d / ItemDef 追加 %d / 既存更新 %d' % (new_groups, added, updated))

    if a.compare:
        # 作り直したものが手元の define.xml と同じかを見る。CreationDateTime だけは回ごとに
        # 変わるので、その属性を伏せてから1バイトずつ比べる。
        if not os.path.exists(a.compare):
            raise SystemExit('突き合わせる相手がありません: %s' % a.compare)
        stamp = re.compile(r'CreationDateTime="[^"]*"')
        made = stamp.sub('CreationDateTime=""', open(out_xml, 'rb').read().decode('utf-8'))
        have = stamp.sub('CreationDateTime=""', open(a.compare, 'rb').read().decode('utf-8'))
        if made != have:
            print('作り直した define.xml が %s と違います' % a.compare)
            return 1
        print('突き合わせ: %s と一致（CreationDateTime を除いて %d バイト）'
              % (a.compare, len(made.encode('utf-8'))))
    return 0


def odm_study_oid(odm):
    return kid(odm, 'Study').getAttribute('OID')


if __name__ == '__main__':
    sys.exit(main())
