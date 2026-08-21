"""ADaM の define.xml（Define-XML 2.0.0）を変数マップと Dataset-JSON から作る。

ADaM には受領 define.xml が無いので新規生成になる。入力は3つ。

- 変数マップ（`--variable-map`）… `label_en`・`origin`・`predecessor`・`spec_ref` を手で維持する
  CSV。**ラベルと Origin の正本**。ADaM の変数はラベルの出どころが3種類（ADaM IG・転記元の
  SDTM IG・試験固有）に分かれるので、IG からは引けない
- Dataset-JSON（`--json-dir`）… 変数の型・長さ・ラベル・順序。ADaM を作るプログラムの出力
- ADaM IG の変数一覧（`--adam-ig`）… `ItemRef/@Mandatory` の判定に使う。
  `export-adam-metadata.py` が CDISC Library の写しから作る

試験ごとに変わるものは引数と CSV が持つ。スクリプトが持つのは Define-XML 2.0.0 の骨格と、
ADaM の標準に沿う `def:Class` / `def:Structure`（下の DS_META）だけ。試験固有のデータセットは
`--dataset-meta` の CSV で足す。CodeList は `--codelist` の CSV が持つ。

言語は英語のみ。日本語のラベルを入れるとラベルの正本が2つになるので入れない。

    python build-adam-define.py --json-dir <Dataset-JSON のディレクトリ> \
        --variable-map docs/variable-map.csv --adam-ig docs/adamig-1-1-variables.csv \
        --codelist docs/adam-codelist.csv --out <出力する define.xml> \
        --study-oid STUDY-001 --study-name STUDY-001 \
        --study-description "..." --protocol-name "..." \
        --originator "..." --xsl-from <SDTM 側の define2-0-0.xsl>
"""
import argparse
import csv
import datetime
import fnmatch
import glob
import json
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# データセットの Class と Structure（ADaM IG）。ADaM の標準に沿うので試験ごとに変えない。
# 試験固有のデータセットは --dataset-meta の CSV（dataset,class,structure,repeating）で足す。
DS_META = {
    'ADSL':  ('SUBJECT LEVEL ANALYSIS DATASET', 'One record per subject', 'No'),
    'ADTTE': ('BASIC DATA STRUCTURE', 'One record per subject per parameter', 'Yes'),
    'ADRS':  ('BASIC DATA STRUCTURE', 'One record per subject per parameter per assessment', 'Yes'),
    'ADLB':  ('BASIC DATA STRUCTURE', 'One record per subject per parameter per assessment', 'Yes'),
    'ADVS':  ('BASIC DATA STRUCTURE', 'One record per subject per parameter per assessment', 'Yes'),
    'ADEC':  ('BASIC DATA STRUCTURE', 'One record per subject per parameter per exposure record', 'Yes'),
    'ADAE':  ('OCCURRENCE DATA STRUCTURE', 'One record per subject per adverse event', 'Yes'),
    'ADCM':  ('OCCURRENCE DATA STRUCTURE', 'One record per subject per medication record', 'Yes'),
    'ADMH':  ('OCCURRENCE DATA STRUCTURE', 'One record per subject per medical history record', 'Yes'),
}
DS_DEFAULT = ('ADAM OTHER', 'One record per subject', 'Yes')

# Dataset-JSON の型 → Define-XML の DataType
DTYPE = {'string': 'text', 'float': 'float', 'integer': 'integer', 'date': 'date',
         'datetime': 'datetime', 'time': 'time', 'decimal': 'float', 'boolean': 'text'}

# OCCDS（ADAE・ADCM・ADMH）は ADaM IG 1.1 の範囲外なので識別子だけを Required とする
REQ_OCCDS = [('STUDYID', None), ('USUBJID', None)]

ODM = 'http://www.cdisc.org/ns/odm/v1.3'
DEF = 'http://www.cdisc.org/ns/def/v2.0'
XLINK = 'http://www.w3.org/1999/xlink'
XML_LANG = '{http://www.w3.org/XML/1998/namespace}lang'
ET.register_namespace('', ODM)
ET.register_namespace('def', DEF)
ET.register_namespace('xlink', XLINK)


def Q(ns, tag):
    return f'{{{ns}}}{tag}'


def read_csv(path):
    if not os.path.exists(path):
        raise SystemExit(f'CSV がありません: {path}')
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def desc(parent, text):
    d = ET.SubElement(parent, Q(ODM, 'Description'))
    tt = ET.SubElement(d, Q(ODM, 'TranslatedText'))
    tt.set(XML_LANG, 'en')
    tt.text = text
    return d


# --- 入力を読む ---------------------------------------------------------------------

def load_variable_map(path, layer):
    """変数マップから 1 層を読む。キーは (データセット, 変数)。"""
    vm = {}
    for r in read_csv(path):
        if layer and (r.get('layer') or '') != layer:
            continue
        vm[((r.get('dataset') or '').strip().upper(), (r.get('variable') or '').strip())] = r
    if not vm:
        raise SystemExit(f'{path} に layer={layer} の行がありません')
    return vm


def load_dataset_meta(path):
    """DS_META を試験固有のデータセットで拡張する（同名は CSV が勝つ）。"""
    meta = dict(DS_META)
    if not path:
        return meta
    added = []
    for r in read_csv(path):
        name = (r.get('dataset') or '').strip().upper()
        if not name:
            continue
        if name not in meta:
            added.append(name)
        meta[name] = ((r.get('class') or DS_DEFAULT[0]).strip(),
                      (r.get('structure') or DS_DEFAULT[1]).strip(),
                      (r.get('repeating') or DS_DEFAULT[2]).strip())
    if added:
        print(f'試験固有のデータセット {len(added)} 件を足した: ' + ', '.join(added))
    return meta


def load_datasets(json_dir, order):
    """Dataset-JSON を読む。ITEMGROUPDATASEQ は CORE のリーダー用の列なので落とす。"""
    out = []
    for p in sorted(glob.glob(os.path.join(json_dir, '*.json'))):
        d = json.load(open(p, encoding='utf-8'))
        cols = [c for c in d['columns'] if c['name'] != 'ITEMGROUPDATASEQ']
        out.append((d['name'].upper(), d.get('label', ''), cols, d.get('records')))
    if not out:
        raise SystemExit(f'{json_dir} に Dataset-JSON がありません')
    out.sort(key=lambda x: order.index(x[0]) if x[0] in order else len(order))
    return out


def load_required(path):
    """ADaM IG が Required とする変数を ADSL 群と BDS 群に分けて読む。

    IG はデータセットではなく変数グループ単位で定めるので、データセットの Class ごとに
    引く群を変える。TRTxxP のようなパターンは regex 列で照合する。
    """
    adsl, bds = [], []
    for r in read_csv(path):
        if (r.get('core') or '') != 'Req':
            continue
        tgt = adsl if (r.get('group') or '').startswith('ADSL') else bds
        rx = (r.get('regex') or '').strip()
        tgt.append((r['variable'], re.compile(rx) if rx else None))
    if not adsl and not bds:
        raise SystemExit(f'{path} に core=Req の行がありません')
    return adsl, bds


def load_included_items(spec, base_dir):
    """他の CSV から CodeList の項目を引く。

    書式 : include:<CSV>|<値の列>|<Decode の列>[|<列>=<値>][|<列>~<部分一致>]

    値の正本が別の CSV にある CodeList のために置く。写すと二重管理になるので参照する。
    パスは CodeList の CSV から見た相対で書く。
    """
    parts = [p.strip() for p in spec.split('|')]
    if len(parts) < 3:
        raise SystemExit(f'include の書式が違います（列が3つ未満）: {spec}')
    path, ccol, dcol = parts[0], parts[1], parts[2]
    filters = []
    for f in parts[3:]:
        if not f:
            continue
        if '~' in f and ('=' not in f or f.index('~') < f.index('=')):
            col, val = f.split('~', 1)
            filters.append((col.strip(), val.strip(), True))
        elif '=' in f:
            col, val = f.split('=', 1)
            filters.append((col.strip(), val.strip(), False))
        else:
            raise SystemExit(f'include の絞り込みが読めません: {f}')
    if not os.path.isabs(path):
        path = os.path.join(base_dir, path)
    items = []
    for r in read_csv(path):
        ok = True
        for col, val, partial in filters:
            got = r.get(col)
            if got is None:
                raise SystemExit(f'{path} に列 {col} がありません')
            ok = ok and (val in got if partial else got.strip() == val)
        if ok:
            items.append(((r.get(ccol) or '').strip(), (r.get(dcol) or '').strip()))
    if not items:
        raise SystemExit(f'{path} に該当する行がありません: {spec}')
    return items


def load_codelists(path):
    """CodeList の定義と、変数 → CodeList の対応を CSV から読む。

    列 : codelist_oid, codelist_name, datatype, variables, coded_value, decode, source

    codelist_name と datatype は CodeList ごとに1回書けばよい（最後の非空を採る）。
    variables は空白区切りで、`*` を含む項目はパターンとして扱う。パターンは
    ADaM のフラグ変数の約束（文字型・長さ1）を満たす変数にだけ当てる。完全一致が優先。
    coded_value が include: で始まる行は他の CSV から項目を引く。
    出力の順序は CSV に現れた順。
    """
    if not path:
        return {}, {}, []
    base = os.path.dirname(os.path.abspath(path))
    cls, exact, patterns = {}, {}, []
    for r in read_csv(path):
        oid = (r.get('codelist_oid') or '').strip()
        if not oid:
            continue
        e = cls.setdefault(oid, {'name': oid, 'datatype': 'text', 'items': []})
        if (r.get('codelist_name') or '').strip():
            e['name'] = r['codelist_name'].strip()
        if (r.get('datatype') or '').strip():
            e['datatype'] = r['datatype'].strip()
        for v in (r.get('variables') or '').split():
            if any(ch in v for ch in '*?['):
                if (v, oid) not in patterns:
                    patterns.append((v, oid))
            elif v in exact and exact[v] != oid:
                raise SystemExit(f'変数 {v} に CodeList が2つ割り当てられています: '
                                 f'{exact[v]} と {oid}')
            else:
                exact[v] = oid
        code = (r.get('coded_value') or '').strip()
        if code.startswith('include:'):
            e['items'].extend(load_included_items(code[len('include:'):], base))
        elif code:
            e['items'].append((code, (r.get('decode') or '').strip()))
    empty = [o for o, e in cls.items() if not e['items']]
    if empty:
        raise SystemExit('項目が無い CodeList があります: ' + ', '.join(empty))
    print(f'CodeList の定義 {len(cls)} 件・項目 {sum(len(e["items"]) for e in cls.values())} 件'
          f'（変数の割り当て: 完全一致 {len(exact)} / パターン {len(patterns)}）')
    return cls, exact, patterns


# --- 判定 ---------------------------------------------------------------------------

def is_required(cls, variable, req_adsl, req_bds):
    """その Class で IG が Required とする変数か。TRTxxP のようなパターンも照合する。"""
    if cls.startswith('SUBJECT LEVEL'):
        cand = req_adsl
    elif cls.startswith('BASIC'):
        cand = req_bds
    else:
        cand = REQ_OCCDS
    for nm, rx in cand:
        if rx.match(variable) if rx else variable == nm:
            return True
    return False


def codelist_for(col, exact, patterns):
    """変数に当てる CodeList の OID。無ければ None。"""
    name = col['name']
    if name in exact:
        return exact[name]
    if col.get('dataType') == 'string' and col.get('length') == 1:
        for pat, oid in patterns:
            if fnmatch.fnmatchcase(name, pat):
                return oid
    return None


# --- XML を組む ---------------------------------------------------------------------

def build(a):
    ds_meta = load_dataset_meta(a.dataset_meta)
    vm = load_variable_map(a.variable_map, a.layer)
    print(f'variable-map の {a.layer} 層 {len(vm)} 変数')
    req_adsl, req_bds = load_required(a.adam_ig)
    cls_def, cl_exact, cl_pat = load_codelists(a.codelist)
    datasets = load_datasets(a.json_dir, list(ds_meta))
    print('データセット: ' + ', '.join(
        f'{n}({len(c)}変数/{r}行)' for n, _, c, r in datasets))

    odm = ET.Element(Q(ODM, 'ODM'))
    odm.set('ODMVersion', '1.3.2')
    odm.set('FileType', 'Snapshot')
    odm.set('FileOID', a.file_oid or f'{a.study_oid}.ADaM.define')
    odm.set('CreationDateTime', a.creation_datetime)
    if a.originator:
        odm.set('Originator', a.originator)
    odm.set(Q(DEF, 'Context'), a.context)

    study = ET.SubElement(odm, Q(ODM, 'Study'))
    study.set('OID', a.study_oid)
    gv = ET.SubElement(study, Q(ODM, 'GlobalVariables'))
    ET.SubElement(gv, Q(ODM, 'StudyName')).text = a.study_name or a.study_oid
    ET.SubElement(gv, Q(ODM, 'StudyDescription')).text = a.study_description
    ET.SubElement(gv, Q(ODM, 'ProtocolName')).text = a.protocol_name or a.study_oid

    mdv = ET.SubElement(study, Q(ODM, 'MetaDataVersion'))
    mdv.set('OID', a.mdv_oid or f'MDV.{a.study_oid}.ADaM')
    mdv.set('Name', a.mdv_name or f'ADaM Metadata for {a.study_oid}')
    mdv.set('Description', a.mdv_description)
    mdv.set(Q(DEF, 'DefineVersion'), '2.0.0')
    mdv.set(Q(DEF, 'StandardName'), a.standard_name)
    mdv.set(Q(DEF, 'StandardVersion'), a.standard_version)

    # ItemGroupDef（データセット）
    for name, label, cols, _ in datasets:
        cls, struct, rep = ds_meta.get(name, DS_DEFAULT)
        ig = ET.SubElement(mdv, Q(ODM, 'ItemGroupDef'))
        ig.set('OID', f'IG.{name}')
        ig.set('Name', name)
        ig.set('Repeating', rep)
        ig.set('IsReferenceData', 'No')
        ig.set('SASDatasetName', name)
        ig.set('Purpose', 'Analysis')
        ig.set(Q(DEF, 'Structure'), struct)
        ig.set(Q(DEF, 'Class'), cls)
        ig.set(Q(DEF, 'ArchiveLocationID'), f'LF.{name}')
        desc(ig, label or name)
        for i, c in enumerate(cols, 1):
            ref = ET.SubElement(ig, Q(ODM, 'ItemRef'))
            ref.set('ItemOID', f'IT.{name}.{c["name"]}')
            ref.set('OrderNumber', str(i))
            ref.set('Mandatory',
                    'Yes' if is_required(cls, c['name'], req_adsl, req_bds) else 'No')
        leaf = ET.SubElement(ig, Q(DEF, 'leaf'))
        leaf.set('ID', f'LF.{name}')
        leaf.set(Q(XLINK, 'href'), f'{name.lower()}.{a.leaf_ext}')
        ET.SubElement(leaf, Q(DEF, 'title')).text = f'{name.lower()}.{a.leaf_ext}'

    # ItemDef（変数）
    missing, used_cl = [], set()
    for name, _, cols, _ in datasets:
        for c in cols:
            it = ET.SubElement(mdv, Q(ODM, 'ItemDef'))
            it.set('OID', f'IT.{name}.{c["name"]}')
            it.set('Name', c['name'])
            it.set('DataType', DTYPE.get(c['dataType'], 'text'))
            if c.get('length'):
                it.set('Length', str(c['length']))
            it.set('SASFieldName', c['name'])
            r = vm.get((name, c['name']))
            desc(it, (r.get('label_en') if r and r.get('label_en')
                      else c.get('label') or c['name']))
            cl = codelist_for(c, cl_exact, cl_pat)
            if cl:
                if cl not in cls_def:
                    raise SystemExit(f'{c["name"]} が参照する CodeList {cl} の定義がありません')
                ET.SubElement(it, Q(ODM, 'CodeListRef')).set('CodeListOID', cl)
                used_cl.add(cl)
            if r is None:
                missing.append(f'{name}.{c["name"]}')
                continue
            og = ET.SubElement(it, Q(DEF, 'Origin'))
            og.set('Type', r.get('origin') or 'Derived')
            if r.get('predecessor'):
                desc(og, r['predecessor'])
            elif r.get('spec_ref'):
                desc(og, r['spec_ref'])
    if missing:
        print(f'variable-map に無い変数 {len(missing)} 件: ' + ', '.join(missing[:10]))

    # CodeList（Define-XML 2.0 は ItemDef の後に置く）
    for oid in [o for o in cls_def if o in used_cl]:
        e = cls_def[oid]
        cl = ET.SubElement(mdv, Q(ODM, 'CodeList'))
        cl.set('OID', oid)
        cl.set('Name', e['name'])
        cl.set('DataType', e['datatype'])
        for i, (code, dec) in enumerate(e['items'], 1):
            ci = ET.SubElement(cl, Q(ODM, 'CodeListItem'))
            ci.set('CodedValue', code)
            ci.set('OrderNumber', str(i))
            d = ET.SubElement(ci, Q(ODM, 'Decode'))
            tt = ET.SubElement(d, Q(ODM, 'TranslatedText'))
            tt.set(XML_LANG, 'en')
            tt.text = dec
    unused = [o for o in cls_def if o not in used_cl]
    if used_cl:
        print(f'CodeList {len(used_cl)} 件を載せた: ' + ', '.join(sorted(used_cl)))
    if unused:
        print(f'どの変数からも参照されなかった CodeList {len(unused)} 件: '
              + ', '.join(unused))
    return odm


def verify(path):
    chk = ET.parse(path).getroot()
    ns = {'o': ODM, 'd': DEF}
    print('検証: ItemGroupDef {} / ItemDef {} / Origin {} / CodeList {} / CodeListItem {}'.format(
        len(chk.findall('.//o:ItemGroupDef', ns)),
        len(chk.findall('.//o:ItemDef', ns)),
        len(chk.findall('.//d:Origin', ns)),
        len(chk.findall('.//o:CodeList', ns)),
        len(chk.findall('.//o:CodeListItem', ns))))
    ref = {e.get('CodeListOID') for e in chk.findall('.//o:CodeListRef', ns)}
    have = {e.get('OID') for e in chk.findall('.//o:CodeList', ns)}
    print('参照だけで定義が無い CodeList:', (ref - have) or 'なし')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--json-dir', required=True, help='Dataset-JSON のディレクトリ')
    ap.add_argument('--variable-map', required=True, help='変数マップの CSV')
    ap.add_argument('--adam-ig', required=True,
                    help='ADaM IG の変数一覧 CSV（export-adam-metadata.py の出力）')
    ap.add_argument('--out', required=True, help='出力する define.xml')
    ap.add_argument('--codelist', help='CodeList の定義 CSV')
    ap.add_argument('--dataset-meta', help='試験固有のデータセットの Class・Structure の CSV')
    ap.add_argument('--layer', default='adam', help='変数マップの層（既定 adam。空なら絞らない）')
    ap.add_argument('--study-oid', required=True)
    ap.add_argument('--study-name', help='既定は --study-oid と同じ')
    ap.add_argument('--study-description', default='')
    ap.add_argument('--protocol-name', help='既定は --study-oid と同じ')
    ap.add_argument('--file-oid', help='既定は <study-oid>.ADaM.define')
    ap.add_argument('--mdv-oid', help='既定は MDV.<study-oid>.ADaM')
    ap.add_argument('--mdv-name', help='既定は ADaM Metadata for <study-oid>')
    ap.add_argument('--mdv-description', default='ADaM datasets derived from SDTM')
    ap.add_argument('--originator', default='', help='ODM/@Originator（空なら付けない）')
    ap.add_argument('--context', default='Other', help='def:Context（既定 Other）')
    ap.add_argument('--standard-name', default='ADaM-IG')
    ap.add_argument('--standard-version', default='1.1')
    ap.add_argument('--creation-datetime',
                    default=datetime.date.today().isoformat() + 'T00:00:00',
                    help='ODM/@CreationDateTime（既定は実行日の 00:00:00。'
                         '固定したいときに渡す）')
    ap.add_argument('--leaf-ext', default='json', help='def:leaf が指すファイルの拡張子')
    ap.add_argument('--xsl-href', default='define2-0-0.xsl',
                    help='xml-stylesheet の href（空なら処理命令を付けない）')
    ap.add_argument('--xsl-from', help='この XSL を出力先へ複写する（無ければ何もしない）')
    a = ap.parse_args()

    odm = build(a)
    ET.indent(odm, space='  ')
    xml = ET.tostring(odm, encoding='unicode')
    head = '<?xml version="1.0" encoding="UTF-8"?>\n'
    if a.xsl_href:
        head += f'<?xml-stylesheet type="text/xsl" href="{a.xsl_href}"?>\n'
    outdir = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(outdir, exist_ok=True)
    with open(a.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(head + xml + '\n')
    print(f'{a.out} を書いた（{os.path.getsize(a.out):,} バイト）')

    if a.xsl_from and a.xsl_href:
        dst = os.path.join(outdir, os.path.basename(a.xsl_href))
        if os.path.exists(a.xsl_from) and not os.path.exists(dst):
            shutil.copy2(a.xsl_from, dst)
            print(f'{os.path.basename(dst)} を出力先へ複写した')

    verify(a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
