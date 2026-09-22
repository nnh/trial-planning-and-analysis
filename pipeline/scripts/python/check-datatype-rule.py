# Dataset-JSON・define.xml の dataType を決める規則が3実装で揃っているか見る。
#
# SDTM 層の数値は、定義の上で整数しか取らない変数だけ integer とし、残りは float に
# する。この規則は言語をまたぐため実装が3つに分かれる（R・SAS・Python）。名前の集合が
# ずれると、同じ変数が実装によって別の型になり、Dataset-JSON から読み戻す側で値が
# 丸められる。2026-09-06 に基準範囲を integer としていたため、定量域の下限 0.01 が
# 0 になり分子遺伝学的効果の判定が1件動いた。
#
# 判定は、各実装から接尾辞のトークン集合と完全一致の名前集合を取り出して比べる。
#
#   python scripts/check-datatype-rule.py
#
# 終了コード 0 3実装で揃っている / 1 揃っていない / 2 検査が走らなかった
#   （実装のファイルが無い、または規則を取り出せない）
#
# 2 を 0 と読まない。取り出せないのは実装の書き方が変わったときで、規則が揃っているか
# どうかは分からない。
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# SAS 側の実装はプログラム名に試験 ID を持つ。docs/metadata/trial.json から引く
TRIAL = boxpath.trial_id()

SRC = {
    'R (ap_common.R)': (
        os.path.join(REPO, 'program', 'r', 'ap_common.R'),
        r'grepl\("\(([A-Z|]+)\)\$", vn\)\) return\("integer"\)',
        r'vn %in% c\(([^)]+)\)\) return\("integer"\)',
    ),
    'SAS (SDTMtoJSON.sas)': (
        os.path.join(REPO, 'program', 'sas', '%s_SDTMtoJSON.sas' % TRIAL),
        r'prxmatch\(%str\(/\(([A-Z|]+)\)\$/\)',
        r'((?:or &&vn&i = [A-Z]+\s*)+)%then %do; \'"integer"\}\'',
    ),
    'Python (update-define-xml.py)': (
        os.path.join(REPO, 'scripts', 'update-define-xml.py'),
        r"r'\(([A-Z|]+)\)\$'",
        r"r'\|\^\(([A-Z|]+)\)\$'",
    ),
}

NAME = re.compile(r'[A-Z]{3,}')


def extract(path, re_suffix, re_exact):
    t = open(path, encoding='utf-8').read()
    m = re.search(re_suffix, t)
    if not m:
        return None, None
    suffix = set(m.group(1).split('|'))
    m2 = re.search(re_exact, t)
    exact = set(NAME.findall(m2.group(1))) if m2 else set()
    return suffix, exact


def main():
    got = {}
    ng = 0
    lack = 0
    for label, (path, rs, re_) in SRC.items():
        if not os.path.exists(path):
            print('材料が無い: %s が無い: %s' % (label, path))
            lack += 1
            continue
        suffix, exact = extract(path, rs, re_)
        if suffix is None:
            print('材料が無い: %s から接尾辞の集合を取り出せない（実装の書き方が変わった）' % label)
            lack += 1
            continue
        got[label] = (suffix, exact)

    if lack:
        print('検査が走らなかった。規則が揃っているかは分からない。')
        return 2

    labels = list(got)
    base = got[labels[0]]
    for label in labels[1:]:
        for i, kind in ((0, '接尾辞'), (1, '完全一致の名前')):
            a, b = base[i], got[label][i]
            if a != b:
                print('NG %s の集合が %s と %s で違う' % (kind, labels[0], label))
                if a - b:
                    print('   %s にだけある: %s' % (labels[0], ', '.join(sorted(a - b))))
                if b - a:
                    print('   %s にだけある: %s' % (label, ', '.join(sorted(b - a))))
                ng += 1

    if ng:
        return 1

    print('OK dataType の規則が3実装で揃っている')
    print('   接尾辞: %s' % ', '.join(sorted(base[0])))
    print('   完全一致: %s' % ', '.join(sorted(base[1])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
