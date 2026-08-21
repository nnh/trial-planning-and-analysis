# compare-outputs.py
#
# 移行の前後で成果物が変わっていないかを見る。符号化の違いと実行時刻を吸収して
# 「中身が同じか」だけを判定する。
#
#   python compare-outputs.py <移行前> <移行後>
#   python compare-outputs.py <移行前> <移行後> --full      ... 差分を多めに出す
#   python compare-outputs.py <移行前> <移行後> --ignore "パターン"   ... 無視する行を足す
#
# 値が1つでも変わったら符号化ではなく実装の問題なので、そこで止めて原因を追う。
# RTF・PDF・xlsx は符号化そのものが変わるので、比較の主役にしない
# （RTF は日本語が CP932 セッションでは \'8E\'9E、UTF-8 セッションでは ☗8; になる）。
import sys, os, io, re, hashlib, argparse

# 実行のたびに必ず変わる行
IGNORE = [
    r'datasetJSONCreationDateTime',
    r'sourceSystemVersion',
    r'creatim|revtim',
    r"\\'8E\\'9E",        # RTF ヘッダの実行時刻（CP932 セッション）
    r'\\u26178',          # 同（UTF-8 セッション）
    r'出力日|作成日時',
]


def norm(path):
    """BOM を外してテキストとして返す。読めなければ (None, None)"""
    b = io.open(path, 'rb').read()
    if b.startswith(b'\xef\xbb\xbf'):
        b = b[3:]
    for enc in ('utf-8', 'cp932'):
        try:
            return b.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return None, None


def glob_all(d):
    out = []
    for root, _, files in os.walk(d):
        out += [os.path.join(root, f) for f in files]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('before')
    ap.add_argument('after')
    ap.add_argument('--full', action='store_true')
    ap.add_argument('--ignore', action='append', default=[])
    a = ap.parse_args()
    pats = [re.compile(p) for p in IGNORE + a.ignore]

    def drop(t):
        return '\n'.join(l for l in t.split('\n') if not any(p.search(l) for p in pats))

    A, B = os.path.abspath(a.before), os.path.abspath(a.after)
    fa = {os.path.relpath(p, A) for p in glob_all(A)}
    fb = {os.path.relpath(p, B) for p in glob_all(B)}
    only_a, only_b = sorted(fa - fb), sorted(fb - fa)
    same, diff, bin_diff = [], [], []
    for rel in sorted(fa & fb):
        pa, pb = os.path.join(A, rel), os.path.join(B, rel)
        ta, ea = norm(pa)
        tb, eb = norm(pb)
        if ta is None or tb is None:
            ha = hashlib.sha256(io.open(pa, 'rb').read()).hexdigest()
            hb = hashlib.sha256(io.open(pb, 'rb').read()).hexdigest()
            (same if ha == hb else bin_diff).append(rel)
        elif drop(ta) == drop(tb):
            same.append(rel)
        else:
            diff.append((rel, drop(ta), drop(tb), ea, eb))

    print(f'一致 {len(same)} / 差分 {len(diff)} / バイナリ差分 {len(bin_diff)} '
          f'/ 移行前のみ {len(only_a)} / 移行後のみ {len(only_b)}')
    for r in only_a:
        print('  移行前のみ:', r)
    for r in only_b:
        print('  移行後のみ:', r)
    for r in bin_diff:
        print('  バイナリ差分:', r)
    for rel, ta, tb, ea, eb in diff:
        la, lb = ta.split('\n'), tb.split('\n')
        n = sum(1 for x, y in zip(la, lb) if x != y) + abs(len(la) - len(lb))
        # 行の多重集合が一致するなら違うのは並びだけ。符号化を変えたときに
        # 日本語の表示名で並べている表がこうなる（値は変わっていない）
        note = '  ← 並び順だけ。値は同じ' if sorted(la) == sorted(lb) else ''
        print(f'  差分: {rel}  行数 {len(la)} vs {len(lb)}  異なる行 {n}  符号化 {ea}/{eb}{note}')
        shown = 0
        for i, (x, y) in enumerate(zip(la, lb)):
            if x != y:
                print(f'      {i+1}: 前| {x[:200]}')
                print(f'      {i+1}: 後| {y[:200]}')
                shown += 1
                if shown >= (20 if a.full else 3):
                    break
    if diff or bin_diff:
        print()
        # RTF・PDF・Office 形式は日本語の書き方そのものが符号化で変わるので
        # （CP932 セッションは \'8E\'9E、UTF-8 セッションは \uNNNN;）、
        # 差が出るのが正常。値の突合はテキストの成果物で行う
        repr_ext = ('.rtf', '.pdf', '.xlsx', '.docx', '.doc')
        changed = [(rel, ta, tb) for rel, ta, tb, _, _ in diff
                   if not rel.lower().endswith(repr_ext)]
        represent = [rel for rel, _, _, _, _ in diff if rel.lower().endswith(repr_ext)]

        def same_values(rel, ta, tb):
            """並びを無視して値が同じかを見る。CSV はセル単位、他は行単位で比べる"""
            if rel.lower().endswith('.csv'):
                cells = lambda t: sorted(c for l in t.splitlines() for c in l.split(','))
                return cells(ta) == cells(tb)
            return sorted(ta.splitlines()) == sorted(tb.splitlines())

        order_only = [rel for rel, ta, tb in changed if same_values(rel, ta, tb)]
        real = [rel for rel, ta, tb in changed if not same_values(rel, ta, tb)]
        if represent:
            print(f'書き方だけが変わるもの {len(represent)} 件（RTF 等。日本語の表現が'
                  f'符号化で変わるため差が出るのが正常）: {", ".join(represent[:5])}')
        if order_only:
            print(f'並び順だけが違うもの {len(order_only)} 件。照合順序の変化'
                  f'（CP932 は 無 < 有、UTF-8 は 有 < 無）で、値は変わっていない: '
                  f'{", ".join(order_only[:5])}')
        if real:
            print(f'値が変わったもの {len(real)} 件。符号化ではなく実装の問題なので、'
                  f'ここで止めて原因を追う: {", ".join(real[:5])}')
        if not real:
            print('値が変わったものは無い')

    return 1 if (diff or bin_diff or only_a or only_b) else 0


if __name__ == '__main__':
    sys.exit(main())
