# check-sdtm-declarations.py
#
# define.xml の生成が読む宣言と、SDTM の実データが合っているかを見る。
#
#   docs/metadata/sdtm-value-level.csv      --TESTCD から --TEST（値水準メタデータ）
#   docs/metadata/sdtm-codelist-values.csv  CodeList に載せる値
#   docs/metadata/sdtm-codelist-mode.csv    どの変数をどう合わせるか（replace・add）
#
# CodeList の2本は testcd 列を持つ。空なら変数そのものの CodeList、入っていれば値水準
# （その --TESTCD の行だけ）の CodeList を指す。1つの変数の中で --TESTCD ごとに値の体系が
# 違うときに要る（FA の FAORRES は CTCAE・Glucksberg・中枢神経系白血病の3つを持つ。
# docs/spec/sdtm-spec.md §3.6）。
#
# なぜ要るか。2026-09-05 まで、この2つは scripts/build-sdtm-define-metadata.py が
# 実装系統の Dataset-JSON から毎回作り、update-define-xml.ps1 がそれを読んでいた。
# define は試験に1組で系統を持たないので、生成が読むものを docs/metadata/ の宣言に移した
# （段F。docs/records/sas-to-r-package-migration-20260905.md）。宣言が実データを言い直す形に
# なるので、両者を突き合わせる検査をここに置く。宣言に無い値が実データに出たら止める。
#
# 値水準の対象ドメインは列挙で持たない。<ドメイン>TESTCD と <ドメイン>TEST の両方を持つ
# ドメインという条件がそのまま対象になり、IE の IETESTCD や TS の TSPARMCD は接頭辞が
# ドメイン名でないので当たらない（docs/validation/records/sdtm-conformance-findings-20260815.md D-1）。
#
# 使い方
#   python scripts/check-sdtm-declarations.py                  ... Box の R 系の JSON と照合
#   python scripts/check-sdtm-declarations.py --json-dir <dir> ... 別の Dataset-JSON と照合
#   python scripts/check-sdtm-declarations.py --update         ... 実データの値で宣言を書き直す
#
# --update は固定データが差し替わったときに宣言を作り直すための道で、既定ではない。
# 何が変わるかを git の差分で見てから入れること。
#
# 終了コード 0 全件一致 / 1 食い違いがある / 2 検査が走らなかった（Dataset-JSON か宣言の CSV が無い）
#
# 2 を 0 と読まない。
import argparse
import csv
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath

sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META = os.path.join(REPO, 'docs', 'metadata')
VALUE_LEVEL = os.path.join(META, 'sdtm-value-level.csv')
CODELIST_VALUES = os.path.join(META, 'sdtm-codelist-values.csv')
CODELIST_MODE = os.path.join(META, 'sdtm-codelist-mode.csv')

# CORE のリーダー用の列。変数ではないので数えない
SEQ_COL = 'ITEMGROUPDATASEQ'


def read_csv(path):
    if not os.path.isfile(path):
        print('材料が無い: 宣言の CSV がありません: %s' % path)
        sys.exit(2)
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, cols):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        w = csv.DictWriter(f, fieldnames=cols, quoting=csv.QUOTE_MINIMAL, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def load_json_dir(json_dir):
    """Dataset-JSON をドメイン名で引ける形にする。"""
    paths = sorted(glob.glob(os.path.join(json_dir, '*.json')))
    if not paths:
        print('材料が無い: Dataset-JSON がありません: %s' % json_dir)
        sys.exit(2)
    out = {}
    for p in paths:
        if os.path.basename(p).lower() == 'define.json':
            continue
        with open(p, encoding='utf-8-sig') as f:
            d = json.load(f)
        name = (d.get('name') or '').upper()
        if not name:
            raise SystemExit('name を持たない Dataset-JSON: %s' % p)
        idx = {c['name']: i for i, c in enumerate(d['columns']) if c['name'] != SEQ_COL}
        out[name] = {'idx': idx, 'rows': d.get('rows') or []}
    return out


def value_of(ds, row, var):
    i = ds['idx'].get(var)
    if i is None:
        return ''
    v = row[i]
    return '' if v is None else str(v).strip()


def data_value_level(data):
    """実データの --TESTCD → --TEST。宣言と同じ形（domain・testcd・test）で返す。"""
    rows = []
    for dom in sorted(data):
        ds = data[dom]
        cd, tst = dom + 'TESTCD', dom + 'TEST'
        if cd not in ds['idx'] or tst not in ds['idx']:
            continue
        seen = {}
        for r in ds['rows']:
            k = value_of(ds, r, cd)
            if k:
                seen.setdefault(k, value_of(ds, r, tst))
        for k in sorted(seen):
            rows.append({'domain': dom, 'testcd': k, 'test': seen[k]})
    return rows


def data_codelist_values(data, targets):
    """実データの CodeList の値。targets は (domain, variable, testcd) の一覧。

    testcd が空なら変数そのものの CodeList、入っていれば値水準（その --TESTCD の行だけ）の
    CodeList を指す。1つの変数の中で --TESTCD ごとに値の体系が違うときに要る（FA の
    FAORRES は CTCAE・Glucksberg・中枢神経系白血病の3つを持つ。sdtm-spec.md §3.6）。
    """
    rows = []
    for dom, var, testcd in targets:
        ds = data.get(dom)
        if ds is None:
            raise SystemExit('CodeList の対象ドメインが Dataset-JSON にありません: %s' % dom)
        if var not in ds['idx']:
            raise SystemExit('CodeList の対象変数がありません: %s.%s' % (dom, var))
        key = '%s.%s%s' % (dom, var, '.' + testcd if testcd else '')
        src = ds['rows']
        if testcd:
            cd = dom + 'TESTCD'
            if cd not in ds['idx']:
                raise SystemExit('値水準の CodeList に %s がありません: %s' % (cd, key))
            src = [r for r in src if value_of(ds, r, cd) == testcd]
            if not src:
                raise SystemExit('値水準の CodeList に該当する行がありません: %s' % key)
        vals = sorted({value_of(ds, r, var) for r in src} - {''})
        if not vals:
            raise SystemExit('CodeList の対象変数に値がありません: %s' % key)
        for v in vals:
            rows.append({'domain': dom, 'variable': var, 'testcd': testcd, 'value': v})
    return rows


def compare(name, declared, actual, cols):
    """宣言と実データを突き合わせる。片側にしかない行を挙げる。"""
    d = [tuple(r.get(c) or '' for c in cols) for r in declared]
    a = [tuple(r[c] for c in cols) for r in actual]
    if d == a:
        print('  %s: %d 件 一致' % (name, len(a)))
        return True
    sd, sa = set(d), set(a)
    print('  %s: 一致しません（宣言 %d 件 / 実データ %d 件）' % (name, len(d), len(a)))
    for x in sorted(sa - sd):
        print('    宣言に無い値が実データに出ている: ' + '、'.join(x))
    for x in sorted(sd - sa):
        print('    実データに無い値を宣言している  : ' + '、'.join(x))
    if sd == sa:
        print('    値は同じで並びだけが違う')
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json-dir', help='SDTM の Dataset-JSON（既定 Box の datasets/r/sdtm/json）')
    ap.add_argument('--update', action='store_true',
                    help='実データの値で宣言 CSV を書き直す（既定は照合のみ）')
    a = ap.parse_args()

    json_dir = a.json_dir or os.path.join(boxpath.trial_dir(), 'datasets', 'r', 'sdtm', 'json')
    data = load_json_dir(json_dir)
    print('Dataset-JSON %d ドメイン: %s' % (len(data), json_dir))

    modes = read_csv(CODELIST_MODE)
    targets = []
    for r in modes:
        t = (r.get('testcd') or '').strip()
        key = '%s.%s%s' % (r['domain'], r['variable'], '.' + t if t else '')
        if r['mode'] not in ('replace', 'add'):
            raise SystemExit('%s: mode は replace か add: %s = "%s"'
                             % (CODELIST_MODE, key, r['mode']))
        targets.append((r['domain'], r['variable'], t))
    targets = sorted(targets)

    actual_vl = data_value_level(data)
    actual_cl = data_codelist_values(data, targets)

    if a.update:
        write_csv(VALUE_LEVEL, actual_vl, ['domain', 'testcd', 'test'])
        write_csv(CODELIST_VALUES, actual_cl, ['domain', 'variable', 'testcd', 'value'])
        print('書き直した: %s（%d 件） / %s（%d 件）'
              % (VALUE_LEVEL, len(actual_vl), CODELIST_VALUES, len(actual_cl)))
        print('git の差分で何が変わったかを見てから入れること。')
        return 0

    print('宣言と実データの照合')
    ok = compare('sdtm-value-level.csv', read_csv(VALUE_LEVEL), actual_vl,
                 ['domain', 'testcd', 'test'])
    ok &= compare('sdtm-codelist-values.csv', read_csv(CODELIST_VALUES), actual_cl,
                  ['domain', 'variable', 'testcd', 'value'])
    if not ok:
        print('宣言と実データが合わない。docs/metadata/ の宣言を直すか、'
              '--update で作り直して差分を確かめること。')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
