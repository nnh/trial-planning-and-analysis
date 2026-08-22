# build-crf-field-map.py
#
# Ptosh の eCRF 構造定義 JSON から、帳票・レコード・項目の対応表を作る。
#   docs/crf-field-map.csv    1行が1項目（レコードに載る項目は所属レコードと SDTM 変数つき）
#   docs/crf-option-map.csv   選択肢セットの値（コードと表示名）
#
# Ptosh の JSON が CRF 側の正本である。1つの帳票が SDTM の何レコードを作るか、各レコードの
# どの変数がどの項目から来るか、どの変数に固定値が入るかを、そのまま持っている。
#
#   sheets[].alias_name              帳票スラッグ（--SPID の実値と同じ）
#   sheets[].field_items[]           項目。type が意味を持つ
#       FieldItem::Article           施設が入力する欄
#       FieldItem::Assigned          固定値。default_value が SDTM に入る値（LBTESTCD='WBC' など）
#       FieldItem::Reference         他の帳票の項目を参照して自動で入る欄
#       FieldItem::Heading / Note    見出しと注記。データにはならない
#   sheets[].cdisc_sheet_configs[]   1件が1つの SDTM レコード
#       prefix                       ドメイン（LB・FA・EC …）
#       label                        レコードの通し番号
#       table                        {項目名: 変数の接尾辞}。LB + ORRES → LBORRES
#
# aCRF の HTML（S3）にも同じ注釈が入っているが、そちらは表示用の派生物で、固定値と
# レコードの区切りを持たない。2026-08-20 に両方を突き合わせ、レコードに載る入力欄1277・
# 載らない入力欄58 が完全に一致することを確認したうえで、こちらを正本にした。
#
# 使い方
#   python scripts/build-crf-field-map.py                  ... Box の TMF から最新の JSON を読む
#   python scripts/build-crf-field-map.py --json <path>     ... JSON を指定する
#
# 整合の確認は scripts/check-crf-field-map.py。
import sys, os, csv, glob, json, argparse, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, 'docs', 'crf-field-map.csv')
OUT_OPT = os.path.join(REPO, 'docs', 'crf-option-map.csv')

# ドメイン（変数がどのデータセットにあるか）は variable-map.csv が持つ事実なので写さない。
# 参照先は変数名と、その変数が属するレコードだけを持つ。
COLS = ['sheet_seq', 'sheet_slug', 'sheet_name_ja', 'field_name', 'field_seq', 'field_kind',
        'field_type', 'field_label', 'field_note', 'invisible',
        'record_label', 'sdtm_domain', 'sdtm_variable', 'assigned_value',
        'option_name', 'reference_field']
COLS_OPT = ['option_name', 'code', 'label', 'seq']
KIND = {'FieldItem::Article': 'article', 'FieldItem::Assigned': 'assigned',
        'FieldItem::Reference': 'reference', 'FieldItem::Heading': 'heading',
        'FieldItem::Note': 'note'}


def sdtm_vars():
    """variable-map の SDTM・PV 層にある変数（どのドメインに何があるか）

    Ptosh の table は変数の接尾辞（ORRES・SEX）を持つ。SDTM の変数名は原則
    ドメイン接頭辞つき（LBORRES）だが、DM の SEX・RACE・BRTHDTC のように接頭辞を
    取らないものがある。どちらが実在するかは variable-map が持つ事実なので、それで決める。
    """
    have = collections.defaultdict(set)
    with open(os.path.join(REPO, 'docs', 'variable-map.csv'), encoding='utf-8-sig',
              newline='') as f:
        for r in csv.DictReader(f):
            if r['layer'] in ('sdtm', 'pv'):
                have[r['dataset']].add(r['variable'])
    return have


def sheet_order():
    """aCRF 対応表の並び（CRF の記入順）と帳票名。索引の表示順に使う"""
    order, seq = {}, 0
    for p in sorted(glob.glob(os.path.join(REPO, 'docs', 'tmf', 'aCRF', '*-acrf.csv'))):
        with open(p, encoding='utf-8-sig', newline='') as f:
            for row in csv.reader(f):
                if len(row) < 2 or not row[1].strip():
                    continue
                seq += 1
                slug = row[1].strip().rsplit('/', 1)[-1].replace('.html', '')
                order[slug] = (seq, row[0].strip())
    return order


def newest_json():
    box = boxpath.trial_dir()
    cand = sorted(glob.glob(os.path.join(box, 'TMF', '*.json')))
    if not cand:
        sys.exit(f'Box の TMF に eCRF 定義の JSON が無い（{os.path.join(box, "TMF")}）')
    return cand[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', help='Ptosh の eCRF 構造定義 JSON')
    a = ap.parse_args()
    path = a.json or newest_json()
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    print(f'{os.path.basename(path)} を読んだ（SDTM {d.get("sdtm_version")}・'
          f'CT {d.get("sdtm_terminology_version")}・CTCAE {d.get("ctcae_version")}）')

    order, have = sheet_order(), sdtm_vars()
    rows, opt_rows, miss, unresolved = [], [], [], []
    for sh in d['sheets']:
        slug = sh['alias_name']
        seq, name = order.get(slug, (999, sh.get('name', '')))
        if slug not in order:
            miss.append(slug)
        # 項目 → 所属レコードと変数。Ptosh では1項目が複数レコードに載ることはない
        belong = {}
        for cc in sh.get('cdisc_sheet_configs', []):
            dom = cc['prefix']
            for fld, suf in (cc.get('table') or {}).items():
                d_, v_ = dom, ''
                if suf == '_CO':
                    # Ptosh は SAE の経過記述を CO（Comments）の別レコードとして持つ。本試験は
                    # CO を SDTM から外して PV データ（AE_CO）へ出したので、その名前で解決する
                    # （docs/sdtm-spec.md §3.16）
                    d_, v_, suf = dom + '_CO', 'COVAL', ''
                if suf:
                    v_ = next((c for c in (d_ + suf, suf) if c in have.get(d_, ())), '')
                    if not v_:
                        v_ = d_ + suf
                        unresolved.append(f'{slug}#{fld} {d_} + {suf}')
                belong[fld] = (cc.get('label', ''), d_, v_)
        for f in sh.get('field_items', []):
            kind = KIND.get(f.get('type', ''), f.get('type', ''))
            if kind in ('heading', 'note') and f.get('is_invisible'):
                continue                      # 画面にも出ない見出しは索引に載せない
            rec, dom, var = belong.get(f['name'], ('', '', ''))
            rows.append({
                'sheet_seq': seq, 'sheet_slug': slug, 'sheet_name_ja': name,
                'field_name': f['name'], 'field_seq': f.get('seq', ''), 'field_kind': kind,
                'field_type': f.get('field_type') or '', 'field_label': f.get('label', ''),
                'field_note': (f.get('description') or '').replace('\n', ' ').strip(),
                'invisible': 'Y' if f.get('is_invisible') else '',
                'record_label': rec, 'sdtm_domain': dom, 'sdtm_variable': var,
                'assigned_value': f.get('default_value') if kind == 'assigned' else '',
                'option_name': f.get('option_name') or '',
                'reference_field': f.get('reference_field') or '',
            })
    rows.sort(key=lambda r: (r['sheet_seq'], r['field_seq']))

    for o in d.get('options', []):
        for v in o.get('values', []):
            if v.get('is_usable'):
                opt_rows.append({'option_name': o['name'], 'code': v.get('code', ''),
                                 'label': v.get('name', ''), 'seq': v.get('seq', '')})

    for path_, cols, data in ((OUT, COLS, rows), (OUT_OPT, COLS_OPT, opt_rows)):
        with open(path_, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=cols, lineterminator='\n')
            w.writeheader()
            w.writerows(data)

    k = collections.Counter(r['field_kind'] for r in rows)
    recs = {(r['sheet_slug'], r['record_label'], r['sdtm_domain']) for r in rows
            if r['record_label']}
    art_in = sum(1 for r in rows if r['field_kind'] == 'article' and r['sdtm_variable'])
    art_out = sum(1 for r in rows if r['field_kind'] == 'article' and not r['sdtm_variable'])
    print(f'{OUT} を書いた（{len(rows)} 行）')
    print(f'  帳票 {len({r["sheet_slug"] for r in rows})} / SDTM レコード {len(recs)} / '
          f'項目の種別 ' + ' '.join(f'{a}={b}' for a, b in sorted(k.items())))
    print(f'  入力欄でレコードに載る {art_in} / 載らない {art_out}（SDTM へ出ない）')
    print(f'  ドメイン別のレコード数 ' +
          ' '.join(f'{a}={b}' for a, b in collections.Counter(
              r[2] for r in recs).most_common()))
    print(f'{OUT_OPT} を書いた（選択肢セット {len({r["option_name"] for r in opt_rows})}・'
          f'値 {len(opt_rows)}）')
    if miss:
        print(f'  aCRF 対応表に無い帳票 {len(miss)}: ' + '、'.join(miss))
    if unresolved:
        print(f'  variable-map に無い変数 {len(unresolved)} 件（接頭辞つきで書いた）: '
              + '、'.join(sorted(set(unresolved))[:10]))


if __name__ == '__main__':
    main()
