"""SDTM の define.xml の不備を検出する。

受領 define.xml をもとに作った define.xml には、CDISC CORE で指摘される不備が残りがちで、
CORE の出力メッセージだけでは何をどう直すか分からないことが多い。ここでは define.xml を
直接読んで、直すべき箇所を具体的に挙げる。修正はしない（試験ごとの生成スクリプトが行う）。

検出するもの。

  1. def:Class が Define-XML 2.0 の値セットに無い（FINDINGS ABOUT は 2.1 で追加）
  2. TranslatedText が空（変数ラベル・データセットラベル・リーフのタイトル）
  3. SASFieldName が SAS の変数名として不正（空白を含む・8文字超）
  4. ItemRef の Role が無い、または IG の Role と違う（--roles 指定時）
  5. CodeList に EnumeratedItem と CodeListItem が混在（2.0 では不可）
  6. 複数の変数が同じ CodeList を共有（--TESTCD と --TEST など、受領版でよくある誤り）
  7. 値水準メタデータの参照が壊れている（ItemDef・WhereClauseDef・ItemRef の対応）
  8. Required / Expected 変数の欠落（--roles 指定時）
  9. CodeList の値が実データに無い / 実データの値が CodeList に無い（--data 指定時）
 10. 値水準メタデータの --TESTCD が実データと違う（--data 指定時）

    python check-define-xml.py --define <path/define.xml>
                              [--roles <path/sdtmig-3-2-variable-roles.csv>]
                              [--data <dir>]   # Dataset-JSON か sas7bdat のディレクトリ
                              [--allow-class "FINDINGS ABOUT"]  # 2.1 を許す場合

終了コードは、検出が1件でもあれば 1。9 と 10 は「実データに無い値」を不備として数えない
（CRF の選択肢としては正しいため）。実データにあって define に無い値だけを数える。
"""
import argparse
import csv
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ODM = 'http://www.cdisc.org/ns/odm/v1.3'
DEF = 'http://www.cdisc.org/ns/def/v2.0'
Q = lambda ns, t: f'{{{ns}}}{t}'

# def:Class の値セット。正本は CT の General Observation Class（C103329）で、
#   python export-ct-codelist.py --codelist C103329 --package define-xmlct-<日付> --list
# で確認できる。SDTM は Define-XML 2.0 で使える6語に限る（CORE が 2.0 として検証し、
# FINDINGS ABOUT は 2.1 で追加されたため 2.0 では通らない）。ADaM の構造名は CT の
# 同じコードリストに入っているが 2.0 の値セットには無い。ADaM の define.xml は CORE の
# 検証対象に入れていないので、読み手にとって有益な Class を載せる。
CLASS_20 = {'EVENTS', 'FINDINGS', 'INTERVENTIONS', 'RELATIONSHIP',
            'SPECIAL PURPOSE', 'TRIAL DESIGN'}
CLASS_ADAM = {'ADAM OTHER', 'BASIC DATA STRUCTURE', 'OCCURRENCE DATA STRUCTURE',
              'SUBJECT LEVEL ANALYSIS DATASET', 'DEVICE LEVEL ANALYSIS DATASET',
              'MEDICAL DEVICE BASIC DATA STRUCTURE',
              'MEDICAL DEVICE OCCURRENCE DATA STRUCTURE',
              'REFERENCE DATA STRUCTURE'}
SAS_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,7}$')
VAR_OID = re.compile(r'^IT[.]([A-Z0-9]{2,8})[.]([A-Z0-9]+)$')
VLM_OID = re.compile(r'^IT[.]([A-Z0-9]{2,8})[.]([A-Z0-9]+)[.](.+)$')


def norm_num(v):
    """CodeList の '1000' と実データの 1000.0 を同じ表記にする。"""
    s = str(v).strip()
    try:
        f = float(s)
        return str(int(f)) if f == int(f) else str(f)
    except ValueError:
        return s


def read_data(path):
    """ドメイン → {変数: 値の集合} を返す。Dataset-JSON と sas7bdat を読む。"""
    out = {}
    if not os.path.isdir(path):
        print(f'  --data のディレクトリがありません: {path}')
        return out
    for fn in sorted(os.listdir(path)):
        ext = os.path.splitext(fn)[1].lower()
        dom = os.path.splitext(fn)[0].upper()
        p = os.path.join(path, fn)
        if ext == '.json':
            try:
                with open(p, encoding='utf-8-sig') as f:
                    j = json.load(f)
            except Exception:
                continue
            cols = [c.get('name') for c in j.get('columns', [])]
            if not cols:
                continue
            vals = defaultdict(set)
            for row in j.get('rows', []):
                for nm, v in zip(cols, row):
                    if v is not None and str(v).strip() != '':
                        vals[nm].add(norm_num(v))
            out[j.get('name', dom).upper()] = dict(vals)
        elif ext == '.sas7bdat':
            try:
                import pyreadstat
            except ImportError:
                continue
            df, _ = pyreadstat.read_sas7bdat(p)
            vals = {}
            for c in df.columns:
                s = df[c].dropna()
                vals[c] = {norm_num(x) for x in s if str(x).strip() != ''}
            out[dom] = vals
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--define', required=True)
    ap.add_argument('--roles', help='IG の変数メタデータ CSV（export-sdtm-metadata.py の出力）')
    ap.add_argument('--data', help='Dataset-JSON か sas7bdat のディレクトリ')
    ap.add_argument('--allow-class', action='append', default=[],
                    help='許す def:Class の値（Define-XML 2.1 を使う場合）')
    a = ap.parse_args()

    t = ET.parse(a.define)
    r = t.getroot()
    mdv = r.find(f'.//{Q(ODM, "MetaDataVersion")}')
    if mdv is None:
        raise SystemExit('MetaDataVersion が見つかりません')
    print(f'検査: {a.define}')

    ng = 0
    parent = {c: p for p in mdv.iter() for c in p}
    idefs = {i.get('OID'): i for i in mdv.iter(Q(ODM, 'ItemDef'))}
    igs = list(mdv.iter(Q(ODM, 'ItemGroupDef')))
    std = (mdv.get(Q(DEF, 'StandardName')) or '').upper()
    is_adam = 'ADAM' in std
    cls_ok = (CLASS_ADAM if is_adam else CLASS_20) | set(a.allow_class)

    # 1. def:Class
    print('\n1. def:Class')
    if std:
        print(f'   標準は {std}（{"ADaM" if is_adam else "SDTM"} の値セットで見る）')
    bad = [(g.get('Name'), g.get(Q(DEF, 'Class'))) for g in igs
           if g.get(Q(DEF, 'Class')) and g.get(Q(DEF, 'Class')) not in cls_ok]
    if bad:
        ng += len(bad)
        for nm, c in bad:
            print(f'   {nm}: {c!r} は値セットに無い')
    else:
        print('   問題なし')

    # 2. 空の TranslatedText
    print('\n2. 空の TranslatedText')
    empt = []
    for tt in mdv.iter(Q(ODM, 'TranslatedText')):
        if (tt.text or '').strip():
            continue
        p = parent.get(tt)
        gp = parent.get(p) if p is not None else None
        who = gp.get('OID') or gp.get('Name') if gp is not None else '?'
        empt.append((p.tag.split('}')[-1] if p is not None else '?', who))
    if empt:
        ng += len(empt)
        c = Counter(x[0] for x in empt)
        for k, n in c.most_common():
            ex = [w for t_, w in empt if t_ == k][:4]
            print(f'   {k} の中で {n} 件  例: {", ".join(str(x) for x in ex)}')
    else:
        print('   問題なし')

    # 3. SASFieldName
    print('\n3. SAS 変数名として不正な SASFieldName')
    bad = sorted({i.get('SASFieldName') for i in idefs.values()
                  if i.get('SASFieldName') and not SAS_NAME.match(i.get('SASFieldName'))})
    if bad:
        ng += len(bad)
        for x in bad:
            owners = [o for o, i in idefs.items() if i.get('SASFieldName') == x][:3]
            print(f'   {x!r}  ← {", ".join(owners)}')
    else:
        print('   問題なし')

    # roles CSV
    roleOf, coreOf = {}, {}
    if a.roles:
        with open(a.roles, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                k = f'{row["domain"]}.{row["variable"]}'
                if row.get('role'):
                    roleOf[k] = row['role']
                if row.get('core'):
                    coreOf[k] = row['core']

    # 4. ItemRef の Role
    print('\n4. ItemRef の Role')
    if not roleOf:
        print('   --roles が無いので飛ばす')
    else:
        miss, diff = [], []
        for g in igs:
            dom = g.get('Name')
            for ref in g.findall(Q(ODM, 'ItemRef')):
                it = idefs.get(ref.get('ItemOID'))
                if it is None:
                    continue
                nm = it.get('Name')
                want = roleOf.get(f'{dom}.{nm}')
                got = ref.get('Role')
                if not got:
                    miss.append(f'{dom}.{nm}')
                elif want and got != want:
                    diff.append(f'{dom}.{nm}: define={got} / IG={want}')
        ng += len(miss) + len(diff)
        print(f'   Role が無い: {len(miss)} 件' + (f'  例 {", ".join(miss[:6])}' if miss else ''))
        print(f'   IG と違う  : {len(diff)} 件' + (f'  例 {"; ".join(diff[:4])}' if diff else ''))

    # 5・6. CodeList
    print('\n5. CodeList の EnumeratedItem と CodeListItem の混在')
    cls = list(mdv.iter(Q(ODM, 'CodeList')))
    mixed = [c.get('OID') for c in cls
             if c.findall(Q(ODM, 'EnumeratedItem')) and c.findall(Q(ODM, 'CodeListItem'))]
    if mixed:
        ng += len(mixed)
        print(f'   {len(mixed)} 件: {", ".join(mixed[:6])}')
    else:
        print('   問題なし')

    print('\n6. 複数の変数が共有している CodeList')
    users = defaultdict(list)
    for oid, it in idefs.items():
        ref = it.find(Q(ODM, 'CodeListRef'))
        m = VAR_OID.match(oid or '')
        if ref is not None and m:
            users[ref.get('CodeListOID')].append(f'{m.group(1)}.{m.group(2)}')
    # 変数名が違っても、値集合が同じなら共有は正しい（--PRESP と --BLFL の Y/N、
    # --DOSU と --ORRESU の単位、MedDRA や薬剤辞書など）。--TESTCD を含む共有だけが
    # 明確な誤りで、コード（--TESTCD）と名称（--TEST）は別の値集合であり、ドメインが
    # 違えば --TESTCD の値集合も違う。
    shared = {k: sorted(set(v)) for k, v in users.items()
              if len({x.split('.')[1] for x in v}) > 1}
    bad_share = {k: v for k, v in shared.items()
                 if any(x.split('.')[1].endswith('TESTCD') for x in v)}
    info_share = {k: v for k, v in shared.items() if k not in bad_share}
    if bad_share:
        ng += len(bad_share)
        print(f'   誤り {len(bad_share)} 件（--TESTCD を含む共有）')
        for k, v in list(bad_share.items())[:8]:
            print(f'     {k}: {", ".join(v[:8])}')
    else:
        print('   --TESTCD を含む共有はなし')
    if info_share:
        print(f'   参考 {len(info_share)} 件（値集合が同じなら正しい。目で確かめる）')
        for k, v in list(info_share.items())[:8]:
            print(f'     {k}: {", ".join(v[:6])}' + (' ...' if len(v) > 6 else ''))

    # 7. 値水準メタデータの参照
    print('\n7. 値水準メタデータの参照')
    wcs = {w.get('OID') for w in mdv.iter(Q(DEF, 'WhereClauseDef'))}
    broken = []
    nref = 0
    vlm = defaultdict(set)   # (dom, var) → {testcd}
    for v in mdv.iter(Q(DEF, 'ValueListDef')):
        for ref in v.findall(Q(ODM, 'ItemRef')):
            nref += 1
            oid = ref.get('ItemOID')
            if oid not in idefs:
                broken.append(f'ItemDef なし: {oid}')
                continue
            wr = ref.find(Q(DEF, 'WhereClauseRef'))
            if wr is None:
                broken.append(f'WhereClauseRef なし: {oid}')
                continue
            if wr.get('WhereClauseOID') not in wcs:
                broken.append(f'WhereClauseDef なし: {wr.get("WhereClauseOID")}')
                continue
            m = VLM_OID.match(oid)
            if m:
                vlm[(m.group(1), m.group(2))].add(m.group(3).split('.')[0])
    print(f'   ItemRef {nref} 件 / WhereClauseDef {len(wcs)} 件 / 参照の不備 {len(broken)} 件')
    for x in broken[:6]:
        print(f'     {x}')
    ng += len(broken)

    data = read_data(a.data) if a.data else {}

    # 8. Required / Expected の欠落
    print('\n8. Required / Expected 変数の欠落')
    if not coreOf:
        print('   --roles が無いので飛ばす')
    else:
        for g in igs:
            dom = g.get('Name')
            have = {idefs[ref.get('ItemOID')].get('Name')
                    for ref in g.findall(Q(ODM, 'ItemRef'))
                    if ref.get('ItemOID') in idefs}
            req = {v.split('.')[1] for v, c in coreOf.items()
                   if v.startswith(dom + '.') and c == 'Req'}
            exp = {v.split('.')[1] for v, c in coreOf.items()
                   if v.startswith(dom + '.') and c == 'Exp'}
            mr, me = sorted(req - have), sorted(exp - have)
            if mr:
                ng += len(mr)
                print(f'   {dom}: Required が無い {", ".join(mr)}')
            if me:
                print(f'   {dom}: Expected が無い {", ".join(me)}（不備として数えない）')

    # 9. CodeList と実データ
    print('\n9. CodeList と実データの食い違い')
    if not data:
        print('   --data が無いので飛ばす')
    else:
        clv = {c.get('OID'): {norm_num(e.get('CodedValue'))
                              for e in list(c.findall(Q(ODM, 'EnumeratedItem')))
                              + list(c.findall(Q(ODM, 'CodeListItem')))}
               for c in cls}
        n9 = 0
        for oid, it in sorted(idefs.items()):
            m = VAR_OID.match(oid or '')
            ref = it.find(Q(ODM, 'CodeListRef'))
            if not m or ref is None:
                continue
            dom, var = m.group(1), m.group(2)
            vals = clv.get(ref.get('CodeListOID')) or set()
            actual = (data.get(dom) or {}).get(var)
            if not vals or actual is None:
                continue
            only_dat = sorted(actual - vals)
            if only_dat:
                n9 += 1
                ng += 1
                print(f'   {dom}.{var}: 実データにあって CodeList に無い '
                      f'{", ".join(only_dat[:6])}'
                      + (f' ... 他 {len(only_dat)-6}' if len(only_dat) > 6 else ''))
        if n9 == 0:
            print('   問題なし（CodeList にあって実データに無い値は不備として数えない）')

    # 10. 値水準メタデータと実データ
    print('\n10. 値水準メタデータの --TESTCD と実データ')
    if not data or not vlm:
        print('   --data か値水準メタデータが無いので飛ばす')
    else:
        n10 = 0
        for (dom, var), codes in sorted(vlm.items()):
            cd = f'{dom}TESTCD'
            actual = (data.get(dom) or {}).get(cd)
            if actual is None:
                continue
            only_def = sorted(codes - actual)
            only_dat = sorted(actual - codes)
            if only_def or only_dat:
                n10 += 1
                ng += len(only_def) + len(only_dat)
                print(f'   {dom}.{var}: define のみ {", ".join(only_def) or "なし"} / '
                      f'実データのみ {", ".join(only_dat) or "なし"}')
        if n10 == 0:
            print('   問題なし')

    print(f'\n検出の合計: {ng} 件')
    return 1 if ng else 0


if __name__ == '__main__':
    sys.exit(main())
