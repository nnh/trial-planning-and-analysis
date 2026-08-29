# build-traceability.py
#
# PI 向けのトレーサビリティ索引 output/deliver/r/traceability.html を1ファイルで作る。
# CSS・JS・データをすべて埋め込み、ブラウザだけで開ける状態にする。
#
# 索引は「ノード」と「エッジ」でできている。ノードは追跡の対象（CRF の項目・SDTM の変数・
# ADaM の変数・解析・図表）、エッジは層をまたぐ対応で、それぞれ根拠となる正本が別にある。
# 画面ではどのノードからでも上流・下流へクリックで移動できる。
#
#   CRF 項目 → SDTM 変数    docs/metadata/crf-field-map.csv（aCRF の注釈から生成。値レベルの条件つき）
#   SDTM 変数 → ADaM 変数   docs/metadata/variable-map.csv の predecessor
#   ADaM 変数 → 解析        ARD の由来列（src_data・src_var）。取れない解析は変数名の一致（暫定）
#   解析 → 図表             ARD の output_id と TLF.sas の呼び出し引数
#
# ADaM から解析へのエッジは2種類ある。2026-08-20 に ard_ops.sas へ由来列（SRCDATA・SRCVAR）
# を足したので、data= が ADaM を直に指す解析はその絞り込みごと確定で結べる（画面には
# where 句を出す）。data= が作業データセット（_ae73・_bgfas 等）を指す解析は、そこから
# ADaM へ遡る1段を ARD が持たないため、従来どおり変数名の一致で結び暫定と表示する
# （docs/spec/label-and-traceability-design.md の段階5）。
#
# 入力
#   docs/metadata/variable-map.csv          層をまたいだ変数の対応（手で維持する正本）
#   docs/metadata/crf-field-map.csv         帳票×項目と SDTM の対応（aCRF から生成）
#   docs/metadata/label-catalog.csv         図表の表題・水準・解析項目の表示名
#   docs/tmf/aCRF/*-acrf.csv       aCRF の帳票名と URL（帳票の並び順もこれが持つ）
#   program/sas/<試験ID>_TLF.sas 図表の描画宣言（表番号と解析IDの対応）
#   Box datasets/sas/ard/ard_cards.csv    ARD の実データ（結果値まで）
#   Box datasets/sas/adam/json/*.json      ADaM の PARAMCD・--SPID の実値（値レベルの条件の引き継ぎ用）
#   Box input/rawdata/*.csv        --SPID の実値（ドメインごと）
#
# 外へ出るリンク（aCRF・図表の HTML）は相対パスだけで作る。索引の隣にある置き場所を実際に
# 見て、ファイルが実在するものにだけリンクする。絶対 URL（S3）は使わない——フォルダごと別の
# 場所へ移しても、別の端末へ渡しても切れないようにするため。
#
# 使い方
#   python scripts/build-traceability.py              ... Box へ書く
#   python scripts/build-traceability.py --out x.html ... 出力先を変える
#   python scripts/build-traceability.py --no-box     ... Box 抜きで作る（解析と実値は入らない）
#   --acrf-base / --tlf-base                          ... 置き場所を明示（既定は自動で探す）
import sys, os, csv, json, glob, re, collections, argparse, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = '2026-08-20'

ap = argparse.ArgumentParser()
ap.add_argument('--out')
ap.add_argument('--no-box', action='store_true')
ap.add_argument('--acrf-base',
                help='aCRF の置き場所（索引の置き場所から見た相対パス）。'
                     '省略すると索引の隣を探して自動で決める')
ap.add_argument('--tlf-base',
                help='HTML 版 TLF の置き場所（索引の置き場所から見た相対パス）。'
                     '省略すると索引の隣を探して自動で決める')
args = ap.parse_args()

BOX = None if args.no_box else boxpath.trial_dir(required=False)
OUT = args.out or (os.path.join(BOX, 'output', 'deliver', 'r', 'traceability.html') if BOX
                   else os.path.join(REPO, 'traceability.html'))
OUTDIR = os.path.dirname(os.path.abspath(OUT))

# --- aCRF と図表の置き場所 -------------------------------------------------------------
# 索引から外へ出るリンクは相対パスだけにする。パッケージごとフォルダを移しても、別の端末へ
# 渡しても、Box のどこへ置いても切れないようにするため。絶対 URL（S3）は使わない。
# 置き場所は索引の隣を実際に見て決める。候補は PI パッケージ（ICH E3 の番号）と作業用の
# output/ の2つの並びで、どちらも同じスクリプトで作れるようにしてある。
# 作業用の並びでは索引が output/deliver/r/ にあり、図表は output/tlf/r-<言語>/ にある
# （実装系統と言語でディレクトリを分ける。方針の正本は nnh/trial-planning-and-analysis の
# pipeline/analysis-pipeline-plan.md「フォルダ構成と命名規則」）。パッケージ内は言語だけで
# 分ければ足りるので 14_tlf/<言語> のままにする（納品するのは R 系の1系統だけ）。
ACRF_CAND = ['16_1_2_acrf', 'acrf', os.path.join('..', '..', '..', 'input', 'acrf'),
             os.path.join('..', 'input', 'acrf')]
TLF_CAND = [os.path.join('14_tlf', 'ja'), os.path.join('..', '..', 'tlf', 'r-ja'),
            os.path.join('14_tlf', 'en'), os.path.join('..', '..', 'tlf', 'r-en')]


def resolve_base(given, cands):
    """索引の隣にある置き場所を返す（HTML が1つ以上あるフォルダ）。無ければ空"""
    if given is not None:
        return given.strip().rstrip('/').replace('\\', '/')
    for c in cands:
        if glob.glob(os.path.join(OUTDIR, c, '*.html')):
            return c.replace('\\', '/')
    return ''


ACRF_BASE = resolve_base(args.acrf_base, ACRF_CAND)
TLF_BASE = resolve_base(args.tlf_base, TLF_CAND)

# 全図表が1ページに入った HTML（言語ごとに1本）。個別の図表とは別物で、全体像を先に
# 眺めたいときの入口になる。置き場所はパッケージなら 14_tlf/ 直下、作業用なら索引と同じ
# フォルダで、名前は <試験ID>_TLF_<日付>_<言語>[_r].html。同じ言語が複数あれば
# 名前の並びで最後のもの（日付が新しいもの）を採る
def whole_cands(lang):
    return ['14_tlf', os.path.join('..', '..', 'tlf', 'r-' + lang), '']


def whole_tlf(lang):
    for c in whole_cands(lang):
        hits = sorted(p for p in glob.glob(os.path.join(OUTDIR, c, '*_TLF_*.html'))
                      if re.search(r'_' + lang + r'(_r)?\.html$', os.path.basename(p)))
        if hits:
            return os.path.relpath(hits[-1], OUTDIR).replace(os.sep, '/')
    return ''


WHOLE = {lang: whole_tlf(lang) for lang in ('ja', 'en')}

# 仕様書の HTML（scripts/build-spec-html.py が docs の md から作るもの）。変数の spec_ref
# （`sdtm-spec.md §3.7`）と解析の output_id（`Out-5.2.1`）から節へ直接リンクする。節の id は
# 生成した HTML を実際に読んで拾い、実在する節だけリンクする（無い節へは飛ばさない）
# パッケージなら 16_1_9_methods、作業用なら output/spec（索引は output/deliver/r/ にある）
SPEC_CAND = ['16_1_9_methods', 'spec', os.path.join('..', '..', 'spec')]
SPEC_BASE = ''
SPEC_IDS = {}
for c in SPEC_CAND:
    hits = sorted(glob.glob(os.path.join(OUTDIR, c, '*-spec*.html')) +
                  glob.glob(os.path.join(OUTDIR, c, '*-derivation.html')))
    if not hits:
        continue
    SPEC_BASE = c.replace('\\', '/')
    for h in sorted(glob.glob(os.path.join(OUTDIR, c, '*.html'))):
        with open(h, encoding='utf-8') as f:
            SPEC_IDS[os.path.basename(h)] = set(re.findall(r'id="(s-[^"]+)"', f.read()))
    break


def spec_url(ref):
    """spec_ref（`sdtm-spec.md §3.7`・`ars-spec-index.md Out-5.2.1`）を相対リンクへ。

    HTML が同梱されていないファイル、節が実在しない参照は空を返す（節だけが無いときは
    ファイルの先頭へ向ける。仕様書そのものは読めた方がよい）。
    """
    if not SPEC_BASE or not ref:
        return ''
    m = re.match(r'^(\S+\.md)(?:\s+§?(\S+))?$', ref.strip())
    if not m:
        return ''
    name = os.path.basename(m.group(1))[:-3] + '.html'
    if name not in SPEC_IDS:
        return ''
    url = SPEC_BASE + '/' + name
    sec = 's-' + m.group(2) if m.group(2) else ''
    return url + '#' + sec if sec and sec in SPEC_IDS[name] else url


def local_html(base, name):
    """<base>/<name>.html が索引の隣に実在すればその相対パスを返す。無ければ空。

    リンクを出す前に実在を確かめる。索引が図表や帳票を持たない配布物にも入るため、
    無いものへのリンクを作らないことを生成の時点で保証する。
    """
    if not base:
        return ''
    rel = base.rstrip('/') + '/' + name + '.html'
    return rel if os.path.exists(os.path.join(OUTDIR, rel.replace('/', os.sep))) else ''


def rd(name):
    # 機械が読む定義は docs/metadata/ に置く（下に external/・trial-design/）
    with open(os.path.join(REPO, 'docs', 'metadata', name),
              encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


# =========================================================================================
# 1. リポジトリ側の入力
# =========================================================================================
vm = rd('variable-map.csv')
fm = rd('crf-field-map.csv')
lc = rd('label-catalog.csv')

titles, subtitles, rowlbls, levels, items, stats = {}, {}, {}, {}, {}, {}
for r in lc:
    e = {'en': r['label_en'], 'ja': r['label_ja'], 'src': r['source']}
    {'title': titles, 'subtitle': subtitles, 'rowlbl': rowlbls,
     'level': levels, 'bgitem': items}.get(r['kind'], {})[r['key']] = e
    # 統計量は ARD 側が英語の表示名（stat_label）を持っており、それがカタログの label_en と
    # 同じ文字列なので、英語名で引けるようにしておく（キーは ARD に入っていない）
    if r['kind'] == 'stat' and r['label_en']:
        stats[r['label_en']] = e

# 変数名 → データセット。crf-field-map は変数名だけを持ち、所属は variable-map が持つ
where = collections.defaultdict(set)
for r in vm:
    if r['layer'] in ('sdtm', 'pv'):
        where[r['variable']].add((r['layer'], r['dataset']))


def resolve(var):
    ds = where.get(var, set())
    if len(ds) == 1:
        return next(iter(ds))
    hit = {d for d in ds if var.startswith(d[1])}
    return next(iter(hit)) if len(hit) == 1 else (None, None)


sdtm = [{'ds': r['dataset'], 'v': r['variable'], 'lab': r['label_en'],
         'org': r['origin'], 'ref': r['spec_ref'],
         'refurl': spec_url(r['spec_ref'])} for r in vm if r['layer'] == 'sdtm']
adam = [{'ds': r['dataset'], 'v': r['variable'], 'lab': r['label_en'], 'org': r['origin'],
         'pre': [x.strip() for x in r['predecessor'].split('/') if x.strip()],
         'ref': r['spec_ref'],
         'refurl': spec_url(r['spec_ref'])} for r in vm if r['layer'] == 'adam']
pv = [{'ds': r['dataset'], 'v': r['variable'], 'lab': r['label_en'],
       'org': r['origin'], 'ref': r['spec_ref'],
       'refurl': spec_url(r['spec_ref'])} for r in vm if r['layer'] == 'pv']

# --- 帳票（並び順は aCRF 対応表のとおり。CRF の記入順で PI に見せる） ---
sheets = []
for p in sorted(glob.glob(os.path.join(REPO, 'docs', 'tmf', 'aCRF', '*-acrf.csv'))):
    with open(p, encoding='utf-8-sig', newline='') as f:
        for row in csv.reader(f):
            if len(row) < 2 or not row[1].strip():
                continue
            url = row[1].strip()
            slug = re.sub(r'\.html$', '', url.rsplit('/', 1)[-1])
            # 対応表が持つ URL（S3）は帳票の識別に使うだけで、リンクには使わない。
            # 索引が見るのは索引の隣に同梱した aCRF だけ（相対パス）。
            sheets.append({'slug': slug, 'name': row[0].strip(),
                           'url': local_html(ACRF_BASE, slug)})

# --- 帳票の項目とレコード ---------------------------------------------------------------
# Ptosh は1つの帳票から作る SDTM レコードを定義しており、各レコードは固定値（--TESTCD 等）と
# 入力欄から入る変数でできている。索引もその単位で持つ。1レコード＝1ノード。
IDSUF = ('TESTCD', 'OBJ', 'TRT', 'TERM', 'DECOD', 'CAT', 'SPEC', 'PARMCD', 'SPID')
fields, recs = [], collections.OrderedDict()
for r in fm:
    fields.append({
        'sl': r['sheet_slug'], 'fid': r['field_name'], 'seq': int(r['field_seq'] or 0),
        'lab': r['field_label'], 'note': r['field_note'], 'kind': r['field_kind'],
        'typ': r['field_type'], 'inv': r['invisible'], 'opt': r['option_name'],
        'ref': r['reference_field'], 'rec': r['record_label'], 'ds': r['sdtm_domain'],
        'v': r['sdtm_variable'], 'val': r['assigned_value'],
    })
    if not r['record_label'] or not r['sdtm_variable']:
        continue
    k = (r['sheet_slug'], r['record_label'], r['sdtm_domain'])
    rec = recs.setdefault(k, {'sl': r['sheet_slug'], 'lab': r['record_label'],
                              'ds': r['sdtm_domain'], 'fix': [], 'inp': []})
    if r['field_kind'] == 'assigned':
        rec['fix'].append([r['sdtm_variable'], r['assigned_value']])
    else:
        rec['inp'].append([r['sdtm_variable'], r['field_name'], r['field_kind']])
records = list(recs.values())
for rec in records:
    # 識別に効く固定値だけを絞り込みの式に使う（--TEST や単位は式に入れず固定値として見せる）
    rec['cond'] = [[v, val] for v, val in rec['fix'] if v.endswith(IDSUF)]

opts = collections.OrderedDict()
for r in rd('crf-option-map.csv'):
    opts.setdefault(r['option_name'], []).append([r['code'], r['label']])

# --- 図表（宣言の正本は docs/metadata/tlf-index.csv。表番号 lblid が図表の識別子で、そこから解析へ
#     繋がる）。2026-08-21 まで TLF.sas を正規表現で解析していたが、SAS 側も CSV から読む
#     形にしたので同じ正本を読む（docs/spec/tlf-declaration-design.md）---
disp = []
for r in rd('tlf-index.csv'):
    lblid = r['lblid']
    if not lblid:
        continue
    disp.append({'id': lblid, 'macro': r['display'], 'seq': r['seq'],
                 'kind': 'figure' if r['display'].startswith('fig_') else 'table',
                 'an': r['analysis_id'], 'oid': r['output_id'], 'paramcd': r['paramcd'],
                 # KM の図は ARD の結果値ではなく ADTTE から曲線を描くので解析IDを持たない。
                 # 索引はこの印を見て、解析(ARD)の段を「経由しない」と表示する
                 'direct': bool(r['paramcd'] and not r['analysis_id'] and not r['output_id']),
                 'url': local_html(TLF_BASE, lblid),
                 # 絞り込みは ARD の行（filter）と図の被験者（where）のどちらか
                 'where': r['filter'] or r['where'],
                 'ti': titles.get(lblid, {}), 'su': subtitles.get(lblid, {}),
                 'ro': rowlbls.get(lblid, {})})

# =========================================================================================
# 2. Box 側の入力（ARD の実データと --SPID の実値）
# =========================================================================================
ARD_COLS = ['analysis_id', 'output_id', 'analysis_set', 'data_subset', 'method_id',
            'operation_id', 'group1', 'group1_level', 'variable', 'variable_level',
            'context', 'stat_name', 'stat_label', 'stat_type', 'stat_num', 'stat_char',
            'src_data', 'src_var']
ard_rows, spid, adamv = [], collections.defaultdict(set), {}
dsmeta, dsgrp, ct, items_of = {}, {}, {}, {}
# ARD の解析項目（`EFS`・`Abdominal pain` など）は ADaM の変数名ではなく、行を識別する値の
# ほうと一致する。どの列の実値かを持っておき、索引が解析と ADaM を結ぶのに使う。
ITEMCOLS = ('PARAMCD', 'AETERM', 'AEDECOD')
VALVARS = ('AVAL', 'AVALC', 'CNSR', 'ATOXGR')


def read_define(path, prefix_keys=True):
    """define.xml からデータセットの構造・キー・CodeList を取る。

    レコードの単位（`def:Structure`）とキー変数（`KeySequence`）は CDISC が定めた
    「1レコードが何を表すか」の記述で、変数単位では分からない情報。CodeList はその変数に
    入り得る値（CT）で、値の意味（Decode）を持つものがある。
    """
    try:
        with open(path, encoding='utf-8') as f:
            x = f.read()
    except OSError:
        return

    def at(t, k):
        m = re.search(rf'{k}="([^"]*)"', t)
        return m.group(1) if m else ''

    # CodeList を OID で引けるようにする
    cl = {}
    for a, b in re.findall(r'<CodeList ([^>]*)>(.*?)</CodeList>', x, re.S):
        items = []
        for ia, ib in re.findall(r'<CodeListItem ([^>]*)>(.*?)</CodeListItem>', b, re.S):
            dec = re.search(r'<TranslatedText[^>]*>(.*?)</TranslatedText>', ib, re.S)
            items.append([at(ia, 'CodedValue'), dec.group(1).strip() if dec else ''])
        for ia in re.findall(r'<EnumeratedItem ([^>]*)/?>', b):
            items.append([at(ia, 'CodedValue'), ''])
        cl[at(a, 'OID')] = {'name': at(a, 'Name'), 'n': len(items), 'items': items[:30]}
    # ItemDef → CodeList の対応（ItemOID は IT.LB.LBTESTCD の形）
    for a, b in re.findall(r'<ItemDef ([^>]*)>(.*?)</ItemDef>', x, re.S):
        ref = re.search(r'<CodeListRef CodeListOID="([^"]*)"', b)
        if not ref or ref.group(1) not in cl:
            continue
        parts = at(a, 'OID').split('.')
        if len(parts) >= 3:
            ct[parts[-2] + '.' + parts[-1]] = cl[ref.group(1)]
    for a, b in re.findall(r'<ItemGroupDef ([^>]*)>(.*?)</ItemGroupDef>', x, re.S):
        ks = sorted((int(at(t, 'KeySequence')), at(t, 'ItemOID').split('.')[-1])
                    for t in re.findall(r'<ItemRef [^>]*>', b) if at(t, 'KeySequence'))
        ds = at(a, 'Name').upper()
        dsmeta[ds] = {'cls': at(a, 'def:Class'), 'structure': at(a, 'def:Structure'),
                      'keys': [v for _, v in ks]}


def scan_data(json_dir, group_keys):
    """Dataset-JSON を読み、レコードの型（グループ）ごとに件数・固定値・値の種類を作る。

    グループの分け方は define.xml のキー変数（被験者・来院・日付を除く）に従う。
    LB なら `LBTESTCD`+`LBSPEC` で、その中で全レコード共通の値は実質 assigned value
    （`LBTEST`・`LBCAT`・単位など）なので、それを画面に出せるようにする。
    """
    for p in sorted(glob.glob(os.path.join(json_dir, '*.json'))):
        try:
            with open(p, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        cols = [c['name'] for c in d.get('columns', [])]
        rows = d.get('rows', [])
        ds = (d.get('name') or os.path.basename(p)[:-5]).upper()
        gk = [k for k in group_keys(ds, cols) if k in cols]
        gi = [cols.index(k) for k in gk]
        grp = collections.defaultdict(list)
        for r in rows:
            grp[tuple(str(r[i]) if r[i] is not None else '' for i in gi)].append(r)
        out = {}
        for g, rs in grp.items():
            const, dist = {}, {}
            for i, c in enumerate(cols):
                vals = {r[i] for r in rs if r[i] not in (None, '')}
                if len(vals) == 1:
                    const[c] = str(next(iter(vals)))
                elif 1 < len(vals) <= 6:
                    dist[c] = sorted(str(v) for v in vals)
                elif len(vals) > 6:
                    dist[c] = len(vals)
            out['|'.join(g)] = {'n': len(rs), 'const': const, 'dist': dist}
        dsgrp[ds] = {'k': gk, 'g': out}
        iv = {}
        for c in ITEMCOLS:
            if c in cols:
                vals = sorted({str(r[cols.index(c)]) for r in rows
                               if r[cols.index(c)] not in (None, '')})
                if vals and len(vals) <= 300:
                    iv[c] = vals
        if iv:
            items_of[ds] = {'v': iv, 'tg': [c for c in VALVARS if c in cols]}
        dsmeta.setdefault(ds, {})['n'] = len(rows)


if BOX:
    NOTKEY = {'STUDYID', 'USUBJID', 'VISIT', 'VISITNUM', 'DOMAIN'}
    read_define(os.path.join(BOX, 'datasets', 'sas', 'sdtm', 'define.xml'))
    read_define(os.path.join(BOX, 'datasets', 'sas', 'adam', 'define.xml'))
    scan_data(os.path.join(BOX, 'datasets', 'sas', 'sdtm', 'json'),
              lambda ds, cols: [k for k in dsmeta.get(ds, {}).get('keys', [])
                                if k not in NOTKEY and not k.endswith('DTC')])
    scan_data(os.path.join(BOX, 'datasets', 'sas', 'adam', 'json'),
              lambda ds, cols: ['PARAMCD'] if 'PARAMCD' in cols else [])
    # ADaM の PARAMCD と --SPID の実値。CRF 項目が持つ値レベルの条件（LBTESTCD='MJBCRABL'）を
    # ADaM の行位置（PARAMCD='MJBCRABL'）へ言い換えるのに使う。対応表は持たず実値の一致で決める。
    for ds, gg in dsgrp.items():
        if not ds.startswith('AD'):
            continue
        pc, sp = {}, collections.defaultdict(set)
        for key, g in gg['g'].items():
            if gg['k'] == ['PARAMCD'] and key:
                pc[key] = g['const'].get('PARAM', '')
            for c, v in g['const'].items():
                if c.endswith('SPID'):
                    sp[c].add(v)
            for c, v in g['dist'].items():
                if c.endswith('SPID') and isinstance(v, list):
                    sp[c].update(v)
        adamv[ds] = {'paramcd': pc, 'spid': {k: sorted(v) for k, v in sp.items()}}
    p = os.path.join(BOX, 'datasets', 'sas', 'ard', 'ard_cards.csv')
    if os.path.exists(p):
        with open(p, encoding='utf-8-sig', newline='') as f:
            ard_rows = [{c: (r.get(c) or '') for c in ARD_COLS} for r in csv.DictReader(f)]
    for p in sorted(glob.glob(os.path.join(BOX, 'input', 'rawdata', '*.csv'))):
        dom = os.path.basename(p).replace('.csv', '').upper()
        with open(p, encoding='utf-8-sig', newline='') as f:
            rdr = csv.DictReader(f)
            cols = [c for c in (rdr.fieldnames or []) if c.endswith('SPID')]
            if not cols:
                continue
            for x in rdr:
                v = (x[cols[0]] or '').strip()
                if v:
                    spid[dom].add(v)
    # データセットのラベルは define.xml に無いので受領時の一覧から取る
    p = os.path.join(BOX, 'datasets', 'sas', 'sdtm', 'sdtm_datasets.csv')
    if os.path.exists(p):
        with open(p, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                dsmeta.setdefault(r['dataset'].upper(), {})['label'] = r['label']

# ARD.sas の作成手順から、作業データセット（_ae73 等）が読んでいる ADaM を辿る。
# 由来の宣言を手で書く案は採らない（コードが既に持つ事実の写しになりズレる）。生成時に
# 読む形なら写しを持たないのでズレない（label-and-traceability-design.md の決定事項）。
# 失敗は隠さない。辿れない作業データセットは resolve が空集合を返し、索引に出ない。
def _wds_lineage(path):
    try:
        src = open(path, encoding='utf-8', errors='replace').read()
    except OSError:
        return {}
    txt = re.sub(r'/\*.*?\*/', ' ', src, flags=re.S)          # コメントを落とす
    made = collections.defaultdict(set)

    def _names(clause):
        out = set()
        for tok in re.split(r'[\s,]+', clause):
            tok = re.sub(r'\(.*', '', tok).strip().lower()     # _bgfas(in=a) → _bgfas
            if re.fullmatch(r'[a-z_][a-z0-9_.]*', tok or ''):
                out.add(tok)
        return out

    # run; quit; で step に割り、step ごとに「作る名前」と「読む名前」を対応させる
    for st in re.split(r'(?i)\brun\s*;|\bquit\s*;', txt):
        outs = set()
        for pat in (r'(?i)\bdata\s+([^;]+);', r'(?i)create\s+table\s+([A-Za-z_][A-Za-z0-9_.]*)',
                    r'(?i)\bout\s*=\s*([A-Za-z_][A-Za-z0-9_.]*)'):
            for m in re.findall(pat, st):
                outs |= _names(m)
        ins = set()
        for pat in (r'(?i)\bset\s+([^;]+);', r'(?i)\bmerge\s+([^;]+);',
                    r'(?i)\bfrom\s+([A-Za-z_][A-Za-z0-9_.]*)',
                    r'(?i)\bjoin\s+([A-Za-z_][A-Za-z0-9_.]*)',
                    r'(?i)\bdata\s*=\s*([A-Za-z_][A-Za-z0-9_.]*)'):
            for m in re.findall(pat, st):
                ins |= _names(m)
        for o in outs:
            for i in ins:
                if i != o:
                    made[o].add(i)

    def resolve(name, seen=None):
        seen = seen or set()
        if name in seen:
            return set()
        seen.add(name)
        out = set()
        for p in made.get(name, ()):
            if p.startswith('ads.'):
                out.add(p.split('.', 1)[1].upper())
            elif p.startswith('_'):
                out |= resolve(p, seen)
        return out

    return {w: sorted(resolve(w)) for w in made if w.startswith('_')}


WDS = _wds_lineage(os.path.join(REPO, 'program', 'sas', boxpath.trial_id() + '_ARD.sas'))


# ARD の由来列（src_data）から ADaM のデータセット名と where 句を取り出す。
# 形は `ads.adsl(where=(FASFL='Y' and PNFL='Y'))`。作業データセット（_ae73 等）は
# ADaM ではないのでデータセット名を返さない（ARD からその1段は辿れない）。
def _srcparse(v):
    v = (v or "").strip()
    m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z0-9_]+)", v)
    ds = m.group(2).upper() if m and m.group(1).lower() == "ads" else ""
    w, i = "", v.lower().find("where=(")
    if i >= 0:
        j, d = i + 6, 0
        while j < len(v):
            if v[j] == "(":
                d += 1
            elif v[j] == ")":
                d -= 1
                if d == 0:
                    break
            j += 1
        w = " ".join(v[i + 7:j].split())
    return ds, w


# 解析（1解析＝1行にまとめ、結果値は ARD 実データ側で引く）
an = collections.OrderedDict()
for r in ard_rows:
    a = an.setdefault(r['analysis_id'], {
        'id': r['analysis_id'], 'out': r['output_id'], 'aset': r['analysis_set'],
        'sub': r['data_subset'], 'mth': r['method_id'], 'g1': r['group1'],
        'g1l': set(), 'vars': set(), 'n': 0,
        'srcds': set(), 'srcw': set(), 'srcv': set(),
        'srcvia': set(), 'srcwds': set()})
    if r['src_data']:
        ds, w = _srcparse(r['src_data'])
        if ds:
            a['srcds'].add(ds)
        else:
            # data= が作業データセットのときは ARD.sas の作成手順から ADaM を辿る
            m = re.match(r'\s*(_[A-Za-z0-9_]+)', r['src_data'])
            if m:
                wds = m.group(1).lower()
                if WDS.get(wds):
                    a['srcwds'].add(wds)
                    a['srcvia'].update(WDS[wds])
        if w:
            a['srcw'].add(w)
    for _v in (r['src_var'] or '').split():
        a['srcv'].add(_v)
    if r['group1_level']:
        a['g1l'].add(r['group1_level'])
    if r['variable']:
        a['vars'].add(r['variable'])
    a['n'] += 1
analyses = [dict(a, g1l=sorted(a['g1l']), vars=sorted(a['vars']),
                 srcds=sorted(a['srcds']), srcw=sorted(a['srcw']),
                 srcv=sorted(a['srcv']), srcvia=sorted(a['srcvia']),
                 srcwds=sorted(a['srcwds']),
                 ref='ars-spec-index.md ' + a['out'],
                 refurl=spec_url('ars-spec-index.md ' + a['out'])) for a in an.values()]
n_src = sum(1 for a in analyses if a['srcds'])

# ARD 実データは列を辞書化して埋め込む（行オブジェクトのままだと8MB、辞書化で1MB）
def encode(vals):
    u = sorted(set(vals))
    ix = {v: i for i, v in enumerate(u)}
    return [u, [ix[v] for v in vals]]


ard_enc = {c: encode([r[c] for r in ard_rows]) for c in ARD_COLS} if ard_rows else {}

# =========================================================================================
# 3. 索引の整合（画面の QC 欄に出す。生成物ではなく正本を直すための材料）
# =========================================================================================
adam_names = {a['v'] for a in adam}
# ADaM から解析へのエッジの出所。確定は ARD の由来列が ADaM のデータセットと変数を
# 直に指すもの、暫定は解析項目と ADaM 変数名の一致で結ぶもの。実値の一致（PARAMCD 等）で
# 増える分は画面側で結ぶため、ここには含めない
_apair = {(a['ds'], a['v']) for a in adam}
def _hit(a, key):
    return any((ds, nm) in _apair for ds in a[key] for nm in a['srcv'])


_ndef = sum(1 for a in analyses if _hit(a, 'srcds'))
_nvia = sum(1 for a in analyses if not _hit(a, 'srcds') and _hit(a, 'srcvia'))
_nprov = sum(1 for a in analyses
             if not _hit(a, 'srcds') and not _hit(a, 'srcvia')
             and any(v in adam_names for v in a['vars']))
print(f'ADaM と結ぶ解析: 由来列が ADaM を直に指す {_ndef} / 作業データセット経由で辿った '
      f'{_nvia} / 変数名の一致による暫定 {_nprov} / 結べない '
      f'{len(analyses) - _ndef - _nvia - _nprov} / 計 {len(analyses)}'
      f'。作業データセットの系譜は {len(WDS)} 件を ARD.sas から辿った')
ard_ids = {a['id'] for a in analyses}
ard_outs = {a['out'] for a in analyses}
ard_items = {v for a in analyses for v in a['vars']}
qc = {
    'disp_no_ard': sorted({d['id'] + '（' + d['an'] + '）' for d in disp
                           if d['an'] and d['an'] not in ard_ids}),
    'ard_no_disp': sorted(ard_outs - {d['oid'] for d in disp if d['oid']} -
                          {an[d['an']]['out'] for d in disp if d['an'] in an}),
    'item_no_adam': sorted(ard_items - adam_names),
    'field_nosdtm': sorted(f"{f['sl']}#{f['fid']} {f['lab']}" for f in fields
                           if f['kind'] == 'article' and not f['v']),
    'title_unused': sorted(set(titles) - {d['id'] for d in disp}),
}

DATA = {
    'acrfbase': ACRF_BASE, 'tlfbase': TLF_BASE, 'whole': WHOLE, 'specbase': SPEC_BASE,
    'gen': GEN, 'sheets': sheets, 'fields': fields, 'recs': records, 'opts': opts,
    'sdtm': sdtm, 'adam': adam, 'pv': pv,
    'disp': disp, 'an': analyses, 'ardcols': ARD_COLS if ard_rows else [], 'ard': ard_enc,
    'spid': {k: sorted(v) for k, v in spid.items()}, 'adamv': adamv,
    'dsmeta': dsmeta, 'dsgrp': dsgrp, 'ct': ct, 'items': items_of,
    'lv': levels, 'it': items, 'stl': stats,
    'hasbox': bool(ard_rows),
}
print(f'帳票 {len(sheets)} / 項目 {len(fields)}（うち入力欄 '
      f'{sum(1 for f in fields if f["kind"] == "article")}）/ SDTM レコード {len(records)} / '
      f'SDTM 変数 {len(sdtm)} / ADaM 変数 {len(adam)} / 解析 {len(analyses)} / '
      f'図表 {len(disp)} / ARD 行 {len(ard_rows)}')
# 索引の整合は利用者に見せず、生成時のログで開発側が見る（正本を直すための材料）
QCNOTE = {
    'disp_no_ard': '図表が指す解析IDが ARD に無い（表が出ていない）',
    'ard_no_disp': 'ARD にあるが図表に出ない解析グループ',
    'item_no_adam': 'ADaM 変数名と一致しない解析項目（値の一致で拾えるものを含む）',
    'field_nosdtm': 'SDTM へ出ない入力欄（Ptosh のレコード定義に載っていない）',
    'title_unused': '使われていない図表の表題',
}
print('--- 索引の整合 ---')
for k, v in qc.items():
    if not v:
        continue
    print(f'{QCNOTE.get(k, k)}: {len(v)} 件')
    if len(v) <= 12:
        print('  ' + '、'.join(v))

# ページ本体（HTML・CSS・JS）は scripts/traceability_template.html に置く。
# データの組み立てと画面の作りを別のファイルに分けておくと、どちらも読みやすい。
TPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'traceability_template.html')
with open(TPL, encoding='utf-8') as f:
    HTML = f.read()

html = HTML.replace('__DATA__', json.dumps(DATA, ensure_ascii=False, separators=(',', ':')))
html = html.replace('__GEN__', GEN)
os.makedirs(OUTDIR, exist_ok=True)
open(OUT, 'w', encoding='utf-8', newline='\n').write(html)
print(f'{OUT} を書いた（{os.path.getsize(OUT):,} バイト）')
print('全図表1ページ版: ' + ('、'.join(f'{k} {v}' for k, v in WHOLE.items() if v)
                             or '索引の隣に無いためリンクを出さない'))
if SPEC_BASE:
    n_v = sum(1 for x in sdtm + adam + pv if x['refurl'])
    n_s = sum(1 for x in sdtm + adam + pv if '#' in x['refurl'])
    n_a = sum(1 for a_ in analyses if a_['refurl'])
    print(f'仕様書: {SPEC_BASE}/ へ相対リンク　変数 {n_v}/{len(sdtm) + len(adam) + len(pv)}'
          f'（うち節まで {n_s}）/ 解析 {n_a}/{len(analyses)}')
    ng = sorted({x['ref'] for x in sdtm + adam + pv if x['ref'] and not x['refurl']})
    if ng:
        print('  同梱が無くリンクを出さなかった参照: ' + '、'.join(ng))
else:
    print('仕様書: HTML が索引の隣に無いためリンクを出さない'
          f'（探した場所 {" / ".join(SPEC_CAND)}）')

# 外へ出るリンク（aCRF・図表）の状態。相対パスで実在するものだけリンクしているので、
# ここに出る「リンクなし」は索引の欠陥ではなく同梱物の欠けである。
def link_report(name, base, cands, items):
    have = sum(1 for x in items if x['url'])
    if not base:
        print(f'{name}: 置き場所が索引の隣に無いためリンクを出さない'
              f'（探した場所 {" / ".join(cands)}）')
        return
    print(f'{name}: {base}/ へ相対リンク {have}/{len(items)}')
    ng = [x.get('slug') or x['id'] for x in items if not x['url']]
    if ng:
        print('  同梱が無くリンクを出さなかったもの: ' + '、'.join(ng))


link_report('aCRF', ACRF_BASE, ACRF_CAND, sheets)
link_report('図表', TLF_BASE, TLF_CAND, disp)
