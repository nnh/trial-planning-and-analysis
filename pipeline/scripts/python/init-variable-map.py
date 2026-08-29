# init-variable-map.py
#
# docs/metadata/variable-map.csv の初回版を作る。
#   SDTM 層 : Box datasets/sas/sdtm/sdtm_labels.csv（変数とラベル）と define.xml（Origin）から機械的に起こす
#   ADaM 層 : Box datasets/sas/adam/json/*.json（Dataset-JSON の columns）から変数とラベルを起こす
#   ARD 層  : ard_cards.csv の列（R の {cards} と同じ構成）
#
# predecessor は SDTMtoADaM.sas の導出を読んで判断するものなので、ここでは
# SDTM と同名で転記しているものだけを埋め、残りは空にする。以後 CSV を手で維持する。
# 上書きを避けるため、既存の docs/metadata/variable-map.csv があると何もせず終わる。
import sys, os, glob, json, csv
import xml.etree.ElementTree as ET
sys.stdout.reconfigure(encoding='utf-8')

BOX = os.path.join(os.environ.get('AKIKO_BOX_ROOT', os.path.join(os.environ['USERPROFILE'], 'Box')),
                   r'Stat\Trials\JALSG\<試験ID>')
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, 'docs', 'metadata', 'variable-map.csv')
if os.path.exists(OUT):
    print('既に', OUT, 'があるので何もしない（手で維持する正本を上書きしないため）')
    sys.exit(0)

COLS = ['layer', 'dataset', 'variable', 'label_en', 'origin', 'predecessor',
        'crf_sheet', 'crf_field', 'spec_ref']

# --- SDTM ---
ns = {'o': 'http://www.cdisc.org/ns/odm/v1.3', 'd': 'http://www.cdisc.org/ns/def/v2.0'}
root = ET.parse(os.path.join(BOX, r'datasets\sas\sdtm\define.xml')).getroot()
origin = {}
for it in root.findall('.//o:ItemDef', ns):
    o = it.find('d:Origin', ns)
    if o is not None:
        origin[it.get('OID')] = o.get('Type')

rows = []
with open(os.path.join(BOX, r'datasets\sas\sdtm\sdtm_labels.csv'), encoding='utf-8-sig', newline='') as f:
    for r in csv.DictReader(f):
        rows.append({
            'layer': 'sdtm', 'dataset': r['dataset'].upper(), 'variable': r['variable'],
            'label_en': r['label'], 'origin': origin.get(r['itemOID'], ''),
            'predecessor': '', 'crf_sheet': '', 'crf_field': '',
            'spec_ref': 'sdtm-spec.md',
        })
n_sdtm = len(rows)

# --- ADaM ---
# DM から素通しで転記している識別子と背景。ここだけ predecessor を機械的に置く。
FROM_DM = {'STUDYID': 'DM.STUDYID', 'USUBJID': 'DM.USUBJID', 'SUBJID': 'DM.SUBJID',
           'SITEID': 'DM.SITEID', 'AGE': 'DM.AGE', 'AGEU': 'DM.AGEU',
           'SEX': 'DM.SEX', 'RACE': 'DM.RACE', 'ARM': 'DM.ARM', 'ACTARM': 'DM.ACTARM'}
for f in sorted(glob.glob(os.path.join(BOX, r'datasets\sas\adam\json\*.json'))):
    ds = os.path.basename(f).replace('.json', '').upper()
    d = json.load(open(f, encoding='utf-8'))
    for c in d['columns']:
        nm = c['name']
        if nm == 'ITEMGROUPDATASEQ':      # Dataset-JSON のレコード識別子で ADaM の変数ではない
            continue
        pre = FROM_DM.get(nm, '')
        rows.append({
            'layer': 'adam', 'dataset': ds, 'variable': nm,
            'label_en': c.get('label', ''),
            'origin': 'Predecessor' if pre else '', 'predecessor': pre,
            'crf_sheet': '', 'crf_field': '',
            'spec_ref': 'adam-spec.md',
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
        'origin': 'Derived', 'predecessor': '', 'crf_sheet': '', 'crf_field': '',
        'spec_ref': 'ars-spec-index.md',
    })
n_ard = len(rows) - n_sdtm - n_adam

with open(OUT, 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.DictWriter(f, fieldnames=COLS, lineterminator='\r\n')
    w.writeheader()
    w.writerows(rows)
print(f'{OUT} を作った。sdtm {n_sdtm} / adam {n_adam} / ard {n_ard} = {len(rows)} 行')
