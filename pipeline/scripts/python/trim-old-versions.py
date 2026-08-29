# trim-old-versions.py
#
# 旧版と実行ログを、日付の新しい N 世代だけ残して片付ける。
#
# 生成と片付けを分ける。退避（直下から 旧版/ へ移す）は生成プログラム自身が行い、
# こちらは溜まった世代を落とすだけにする。生成の中に削除を混ぜると、回すたびに
# 過去が消える形になり、いつ何が消えたかを追えない。
#
# 世代のまとめ方は、ファイル名から日付（YYYYMMDD または 09AUG2026 の形）を除いた
# 名前が同じものを1つの系列とみなす。系列ごとに新しい順へ並べ、N 件を残す。
#
# 既定は下見だけで、消すときは --go を付ける。何を消すかを見てから実行する。
#
# 使い方
#   python scripts/trim-old-versions.py                 ... 下見（2世代を残す）
#   python scripts/trim-old-versions.py --go            ... 実行
#   python scripts/trim-old-versions.py --keep 3 --go   ... 3世代を残して実行
import sys, os, re, collections, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

# 片付ける場所。旧版/ を持つフォルダと、実行ログ。
# 図表の 旧版/ は言語と実装系統で4つに分かれる
TARGETS = [
    'output/tlf/r-ja/旧版', 'output/tlf/r-en/旧版',
    'output/tlf/sas-ja/旧版', 'output/tlf/sas-en/旧版',
    'output/compare/旧版',
    'log',
]

DATE = re.compile(r'(20\d{6})|(\d{2}[A-Z]{3}20\d{2})')
MON = {'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04', 'MAY': '05', 'JUN': '06',
       'JUL': '07', 'AUG': '08', 'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12'}


def series_key(name):
    """日付を除いた名前。これが同じものを1つの系列とみなす"""
    return DATE.sub('<date>', name)


def date_key(name):
    """並べ替えのための日付。SAS の 09AUG2026 形式も YYYYMMDD へ直す"""
    m = DATE.search(name)
    if not m:
        return ''
    s = m.group(0)
    if re.match(r'^\d{2}[A-Z]{3}20\d{2}$', s):
        return s[5:9] + MON[s[2:5]] + s[0:2]
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', type=int, default=2, help='残す世代の数（既定 2）')
    ap.add_argument('--go', action='store_true', help='実際に消す（既定は下見だけ）')
    a = ap.parse_args()

    box = boxpath.trial_dir()
    total, n = 0, 0
    for rel in TARGETS:
        d = os.path.join(box, *rel.split('/'))
        if not os.path.isdir(d):
            continue
        files = [f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))]
        g = collections.defaultdict(list)
        for f in files:
            if DATE.search(f):
                g[series_key(f)].append(f)
        drop = []
        for k in sorted(g):
            v = sorted(g[k], key=date_key, reverse=True)
            drop += v[a.keep:]
        if not drop:
            continue
        print(f'{rel}（{len(files)} 件のうち {len(drop)} 件）')
        for f in sorted(drop):
            p = os.path.join(d, f)
            total += os.path.getsize(p)
            n += 1
            print('   ', f)
            if a.go:
                os.remove(p)
    verb = '消した' if a.go else '消せる'
    print(f'{n} 件 / {total / 1024 / 1024:.1f} MB を{verb}'
          + ('' if a.go else '（実行するには --go）'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
