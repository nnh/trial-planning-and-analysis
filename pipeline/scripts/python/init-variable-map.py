# init-variable-map.py
#
# docs/metadata/variable-map.csv の初回版を作る。
#   SDTM 層 : Box datasets/define/sdtm/define.xml（変数・ラベル・宣言長・Origin）から機械的に起こす
#   ADaM 層 : Box datasets/r/adam/json/*.json（Dataset-JSON の columns）から変数とラベルを起こす
#   ARD 層  : ard_cards.csv の列（R の {cards} と同じ構成）
#
# predecessor は SDTMtoADaM.sas の導出を読んで判断するものなので、ここでは
# SDTM と同名で転記しているものだけを埋め、残りは空にする。以後 CSV を手で維持する。
# 上書きを避けるため、既存の docs/metadata/variable-map.csv があると何もせず終わる。
import sys, os, glob, json, csv
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

# 試験フォルダの場所は docs/metadata/trial.json だけが持つ（boxpath.py）。
# 端末ごとに Box の同期先が違うので、ここへ置き場を書かない
BOX = boxpath.trial_dir()
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, 'docs', 'metadata', 'variable-map.csv')
if os.path.exists(OUT):
    print('既に', OUT, 'があるので何もしない（手で維持する正本を上書きしないため）')
    sys.exit(0)

# 列の集合は正本の形。scripts/check-variable-map.py が同じ並びを要求するので、
# 片方だけ足すと検査が「列が無い」で落ちる。宣言長 length と並び order は 2026-09-05 に
# 足した（docs/spec/sdtm-spec.md §2.2.2、docs/spec/adam-spec.md §11）。
COLS = ['layer', 'dataset', 'variable', 'label_en', 'length', 'origin', 'predecessor',
        'crf_sheet', 'crf_field', 'spec_ref', 'order']

# --- SDTM ---
# 変数・ラベル・宣言長・Origin はすべて define.xml が持つ。2026-09-05 まで変数とラベルは
# 別に出力した sdtm_labels.csv から取っていたが、それは define.xml の変数一覧の写しなので、
# 写しを介さず元から引く（段E）。宣言長は ItemDef/@Length で、文字型にだけ付くので数値型は
# 空のままになる。並び（order）は SDTM 標準が定めるので
# docs/metadata/external/sdtm_variable_order.csv が持ち、この CSV には入れない。
ns = {'o': 'http://www.cdisc.org/ns/odm/v1.3', 'd': 'http://www.cdisc.org/ns/def/v2.0'}
root = ET.parse(os.path.join(BOX, 'datasets', 'define', 'sdtm', 'define.xml')).getroot()
itemdef = {}
for it in root.findall('.//o:ItemDef', ns):
    o = it.find('d:Origin', ns)
    d = it.find('o:Description/o:TranslatedText', ns)
    itemdef[it.get('OID')] = {
        'name': it.get('Name'),
        'label': (d.text or '').strip() if d is not None else '',
        'length': it.get('Length') or '',
        'origin': o.get('Type') if o is not None else '',
    }

rows = []
for ig in root.findall('.//o:ItemGroupDef', ns):
    for ir in ig.findall('o:ItemRef', ns):
        it = itemdef.get(ir.get('ItemOID'))
        if it is None:
            continue
        rows.append({
            'layer': 'sdtm', 'dataset': ig.get('Name').upper(), 'variable': it['name'],
            'label_en': it['label'], 'length': it['length'], 'origin': it['origin'],
            'predecessor': '', 'crf_sheet': '', 'crf_field': '',
            'spec_ref': 'sdtm-spec.md', 'order': '',
        })
n_sdtm = len(rows)

# --- ADaM ---
# DM から素通しで転記している識別子と背景。ここだけ predecessor を機械的に置く。
FROM_DM = {'STUDYID': 'DM.STUDYID', 'USUBJID': 'DM.USUBJID', 'SUBJID': 'DM.SUBJID',
           'SITEID': 'DM.SITEID', 'AGE': 'DM.AGE', 'AGEU': 'DM.AGEU',
           'SEX': 'DM.SEX', 'RACE': 'DM.RACE', 'ARM': 'DM.ARM', 'ACTARM': 'DM.ACTARM'}
for f in sorted(glob.glob(os.path.join(BOX, 'datasets', 'r', 'adam', 'json', '*.json'))):
    ds = os.path.basename(f).replace('.json', '').upper()
    d = json.load(open(f, encoding='utf-8'))
    # ADaM IG 1.1 は変数の並びを定めないので、Dataset-JSON の列順を試験の宣言として写す。
    # ITEMGROUPDATASEQ は ADaM の変数ではないので数えない。
    n = 0
    for c in d['columns']:
        nm = c['name']
        if nm == 'ITEMGROUPDATASEQ':      # Dataset-JSON のレコード識別子で ADaM の変数ではない
            continue
        n += 1
        pre = FROM_DM.get(nm, '')
        rows.append({
            'layer': 'adam', 'dataset': ds, 'variable': nm,
            'label_en': c.get('label', ''),
            'length': '' if c.get('length') is None else str(c['length']),
            'origin': 'Predecessor' if pre else '', 'predecessor': pre,
            'crf_sheet': '', 'crf_field': '',
            'spec_ref': 'adam-spec.md', 'order': str(n),
        })
n_adam = len(rows) - n_sdtm

# --- ARD ---
ARD = [
    ('analysis_id',    'Analysis identifier'),
    ('output_id',      'Output (table or figure) identifier'),
    ('analysis_set',   'Analysis set'),
    ('data_subset',    'Data subset'),
    ('method_id',      'Statistical method identifier'),
    ('operation_id',   'Operation identifier'),
    ('group1',         'Grouping variable'),
    ('group1_level',   'Grouping variable level (identifier)'),
    ('variable',       'Analysis variable'),
    ('variable_level', 'Analysis variable level (identifier)'),
    ('context',        'Result context'),
    ('stat_name',      'Statistic name'),
    ('stat_label',     'Statistic label'),
    ('stat_type',      'Statistic type (num or char)'),
    ('stat_num',       'Statistic value (numeric)'),
    ('stat_char',      'Statistic value (character)'),
    ('source',         'Source pipeline (SAS or R)'),
]
for nm, lb in ARD:
    rows.append({
        'layer': 'ard', 'dataset': 'ARD', 'variable': nm, 'label_en': lb,
        'length': '', 'origin': 'Derived', 'predecessor': '',
        'crf_sheet': '', 'crf_field': '',
        'spec_ref': 'ard-spec.md', 'order': '',
    })
n_ard = len(rows) - n_sdtm - n_adam

with open(OUT, 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.DictWriter(f, fieldnames=COLS, lineterminator='\r\n')
    w.writeheader()
    w.writerows(rows)
print(f'{OUT} を作った。sdtm {n_sdtm} / adam {n_adam} / ard {n_ard} = {len(rows)} 行')
