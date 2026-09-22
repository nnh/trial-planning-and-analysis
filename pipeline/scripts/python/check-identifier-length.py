# check-identifier-length.py
#
# 宣言済みの識別子が、SAS 系の ARD の格納長に収まるかを見る。
#
# なぜ要るか。SAS は length で宣言した幅を超えた文字を黙って捨てる。捨てられたことは
# ログにも出ず、ARD の値だけが短くなる。R 側は文字列長の制限を持たないので切れない。
# 結果として同じ解析の data_subset が両系統で別の値になり、二重コーディングの突合か、
# 宣言（docs/validation/acceptance/analysis-set-condition.csv）との照合が落ちる。
# 落ちるのは通し実行の後半なので、原因が「識別子が長すぎた」ことだと分かるまで遠い。
# 2026-09-06 に、2つの治療相をまとめた部分集団の識別子（22文字）が SUBSET $20 で
# 20文字へ切れ、build-ars-json.py の「宣言の無い集団・部分集団」で通し実行が止まった
# （docs/records/decisions-needed-20260901.md の C3-416）。
#
# 見るもの。
#   1. docs/ の宣言が持つ識別子が、その識別子を入れる ARD の列の格納長に収まるか
#   2. 同じ列の length 宣言が ard_ops.sas の中で揃っているか。1つでも狭いものが残ると、
#      そのマクロを通った行だけが切れる（宣言は8箇所以上にある）
#
# 格納長はスクリプトに書かない。program/sas/macro/ard_ops.sas の length 宣言と
# proc sql の as <列> length=<幅> から読む。幅の正本はソースの側だけに置く。
#
# 見ないもの。ARD の実データは見ない。実データを見る検査は Box を要り用にするので、
# 材料の無い端末では飛ばすしかなくなる。ここは宣言だけで完結させ、どの端末でも同じ
# 結果が出るようにする。実行時に組み立てる識別子（An-5.4.3.1-01 のような連番付き、
# An-5.4.4.2-NONHSCT-DAonly のような群名付き）は、宣言が持つのが語幹までなので、
# ここで確かめられるのは語幹の長さである。組み立てた後の値は build-ars-json.py が
# 宣言と突き合わせる段で捕まる。
#
# 材料が無いときは何が無いかを述べて 2 で終える。読む材料はすべてリポジトリの中に
# あり外部の道具に依存しないので、飛ばす口（--allow-skip）は付けない。ファイルが
# 無い・length 宣言が1つも読めない・宣言から識別子が1つも取れないのは、環境の不足
# ではなく検査か正本の側の異常である。
#
#   python scripts/check-identifier-length.py
#   python scripts/check-identifier-length.py --sas <path>   ... 検査自身を試すための口
#
# 終了コード 0 ERROR 無し / 1 ERROR あり / 2 検査が走らなかった（上の材料が無い）
#
# 2 を 0 と読まない。材料が1つでも欠けていれば、見つかった ERROR があっても 2 を返す。
# 一部の列しか見ていない結果を、全体を見た結果として読ませないためである。
import sys, os, re, csv, argparse, collections

sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAS_DEFAULT = os.path.join(REPO, 'program', 'sas', 'macro', 'ard_ops.sas')

# ARD の列と、その列へ入る識別子を宣言している正本。組は
# (CSV への相対パス, 値を持つ列, 縦棒区切りか, 行を絞る条件) である。縦棒区切りの列は
# 1つのセルに複数の識別子が入る（display-contract.csv の分母の宣言など）。
SOURCES = {
    'ANALSET': [
        ('docs/validation/acceptance/analysis-set-condition.csv', 'id', False,
         lambda r: r.get('kind') == 'analysisSet'),
        ('docs/validation/acceptance/display-contract.csv', 'analysis_set', True, None),
    ],
    'SUBSET': [
        ('docs/validation/acceptance/analysis-set-condition.csv', 'id', False,
         lambda r: r.get('kind') == 'dataSubset'),
        ('docs/validation/acceptance/display-contract.csv', 'data_subset', True, None),
        ('docs/metadata/timepoint-map.csv', 'subset', False, None),
        ('docs/metadata/tlf-index.csv', 'subset', False, None),
    ],
    'OUTPUTID': [
        ('docs/metadata/analysis-purpose.csv', 'output_id', False, None),
        ('docs/metadata/tlf-index.csv', 'output_id', False, None),
    ],
    'ANALYSID': [
        ('docs/metadata/analysis-purpose.csv', 'analysis_id', False, None),
        ('docs/metadata/tlf-index.csv', 'analysis_id', False, None),
    ],
    'GROUP1': [
        ('docs/metadata/analysis-grouping.csv', 'grouping_id', False, None),
    ],
    'GROUP1L': [
        ('docs/metadata/analysis-grouping.csv', 'group_id', False, None),
        ('docs/metadata/tlf-index.csv', 'groups', True, None),
    ],
    'LEVELSET': [
        ('docs/metadata/level-sets.csv', 'set_id', False, None),
    ],
    'VARLEVEL': [
        ('docs/metadata/level-sets.csv', 'level', False, None),
    ],
}

# length 宣言の読み取り。data ステップの length 文と、proc sql の as <列> length=<幅> の
# 2つの書き方がある。どちらも同じ列の幅を決めるので、両方を同じ表に集める。
RE_LENGTH_STMT = re.compile(r"\blength\b(.*?);", re.IGNORECASE | re.DOTALL)
RE_NAME_WIDTH = re.compile(r"\b([A-Za-z_][A-Za-z_0-9]*)\s+[$]\s*(\d+)")
RE_AS_LENGTH = re.compile(r"\bas\s+([A-Za-z_][A-Za-z_0-9]*)\s+length\s*=\s*(\d+)",
                          re.IGNORECASE)


def read_widths(path, lack):
    """ard_ops.sas から列ごとの宣言幅を読む。同じ列に複数の宣言があるので集合で返す。"""
    if not os.path.exists(path):
        lack.append('SAS のソースが見つからない: %s。格納長の正本なので、'
                   '無いままでは何も確かめられない' % path)
        return {}
    with open(path, encoding='utf-8') as f:
        src = f.read()
    widths = collections.defaultdict(set)
    n = 0
    for stmt in RE_LENGTH_STMT.findall(src):
        for name, w in RE_NAME_WIDTH.findall(stmt):
            widths[name.upper()].add(int(w))
            n += 1
    for name, w in RE_AS_LENGTH.findall(src):
        widths[name.upper()].add(int(w))
        n += 1
    if not n:
        lack.append('%s から length 宣言を1つも読めなかった。'
                   '書き方が変わったか、読み取りの正規表現が古い' % path)
    return widths


def read_ids(rel, col, split, keep, lack):
    """宣言の CSV から識別子を読む。空欄は宣言が無いという意味なので落とす。"""
    path = os.path.join(REPO, rel)
    if not os.path.exists(path):
        lack.append('宣言の CSV が見つからない: %s' % rel)
        return []
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        lack.append('%s に行が無い' % rel)
        return []
    if col not in rows[0].keys():
        lack.append('%s に %s 列が無い。列の名前が変わったか、検査の側が古い' % (rel, col))
        return []
    out = []
    for r in rows:
        if keep is not None and not keep(r):
            continue
        v = (r.get(col) or '').strip()
        if not v:
            continue
        for one in (v.split('|') if split else [v]):
            one = one.strip()
            if one:
                out.append((one, rel))
    return out


def blen(s):
    """SAS の $n はバイト数なので長さもバイトで測る。識別子は英数字とハイフンだけ
    （identifier-naming-rule.md）なので通常は文字数と一致するが、規則から外れた値が
    混ざったときに短く見積もらないようにする。"""
    return len(s.encode('utf-8'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sas', default=SAS_DEFAULT,
                    help='格納長を読む SAS のソース（既定は program/sas/macro/ard_ops.sas）')
    args = ap.parse_args()

    err, warn, lack = [], [], []
    widths = read_widths(args.sas, lack)
    sasname = os.path.basename(args.sas)
    if not widths:
        # 格納長の正本が読めなければ、どの列も比べられない。列ごとの ERROR を並べると
        # 規則違反が見つかったように読めるので、ここで止める
        for m in lack:
            print('材料が無い: ' + m)
        return 2

    print('格納長の正本: %s' % args.sas)
    for col in sorted(SOURCES):
        ws = sorted(widths.get(col, []))
        # 同じ列の宣言が揃っていなければ、狭い方を通った行だけが切れる
        if len(ws) > 1:
            err.append('%s の length 宣言が揃っていない: %s。狭い宣言を通った行だけが'
                       '切れるので、すべて同じ幅にすること'
                       % (col, '・'.join('$%d' % w for w in ws)))
        if not ws:
            err.append('%s の length 宣言が %s に無い。列の名前が変わったか、'
                       '宣言が落ちている' % (col, sasname))
            continue
        width = ws[0]

        ids = []
        for rel, col_name, split, keep in SOURCES[col]:
            ids.extend(read_ids(rel, col_name, split, keep, lack))
        if not ids:
            lack.append('%s の識別子を宣言から1つも読めなかった。'
                       '0件で通ると検査が効いていないことに気づけない' % col)
            continue

        longest, longest_src = max(ids, key=lambda t: blen(t[0]))
        maxlen = blen(longest)
        over = sorted({(blen(v), v, rel) for v, rel in ids if blen(v) > width},
                      reverse=True)
        for n, v, rel in over:
            err.append('%s $%d に収まらない識別子: %s（%dバイト。%s）。'
                       'SAS 側は %d バイトで切って書き出すので、識別子を短くするか '
                       '%s の length 宣言を広げること'
                       % (col, width, v, n, rel, width, sasname))
        if not over and maxlen > width * 0.8:
            warn.append('%s $%d の余裕が少ない: 最長 %s が %dバイト（%s）'
                        % (col, width, longest, maxlen, longest_src))
        print('  %-9s $%-3d 宣言 %3d 件  最長 %2dバイト  %s'
              % (col, width, len(ids), maxlen, longest))

    for w in warn:
        print('WARN: ' + w)
    for e in err:
        print('ERROR: ' + e)
    for m in lack:
        print('材料が無い: ' + m)
    print('ERROR %d / WARN %d / 材料の不足 %d' % (len(err), len(warn), len(lack)))
    if lack:
        print('検査が走り切っていない。ERROR の件数を全体の結果として読まない。')
        return 2
    return 1 if err else 0


if __name__ == '__main__':
    sys.exit(main())
