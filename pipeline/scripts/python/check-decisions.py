# check-decisions.py
#
# 決定の正本が1つに保たれていることを機械で確かめる。決定が複数の文書に散ると、
# 同じ決定を述べた箇所が別々に古くなる。2026-09-06 までは決定が5箇所に分かれており、
# 主要評価項目の信頼区間の形式は5つの md と1つの CSV の6箇所にあった。表 5.4.3.1 の
# 分母は csr-section-map.md だけが旧規則（FAS 88例固定）のまま残っていた。
#
# 見るのは3つ。
#   1. 一覧が本文と一致するか。一覧は区分ブロックから作るもので、手で維持しない
#   2. 仕様書が決定を述べていないか。述べる代わりに台帳の識別子を引く規則の検査
#   3. 事後の決定が analysis-purpose.csv の reason に現れているか
#
# 使い方
#   python scripts/check-decisions.py           ... 3つとも見る
#   python scripts/check-decisions.py --quiet   ... 失敗した項目だけを出す
import argparse
import csv
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(REPO, 'docs', 'decisions', 'data-handling-decisions.md')
# 決定を述べていないかを見る置き場。台帳のある decisions は除く
SCAN = [os.path.join(REPO, 'docs', d) for d in ('spec', 'reporting', 'input')]
PURPOSE = os.path.join(REPO, 'docs', 'metadata', 'analysis-purpose.csv')

# 枠の節。一覧の対象にしない
FRAME = ('区分', '識別子', '一覧')

# 仕様書が決定を記録しているときの形。日付を伴う確定の言い方で見る。
#
# 「SAP に規定が無い」のような規定の空白を述べる言い方では引かない。空白があること自体は
# 仕様書が書いてよい事実で、違反になるのは、その空白をどう埋めたかをここで決めて記録する
# ことだからである。位置づけの節が「SAP が規定していない箇所をどう扱ったかを記録する」と
# 書くのは役割の説明であって決定ではなく、言い方で当てると区別が付かない。
#
# 拾わないものが3つある。SAP そのものが改訂された旨（「根拠：SAP 5.3.4（2026-08-15 改訂）」）は
# 一次文書の版の記録で、当方の決定ではない。事実が判明した旨も決定ではない。図表番号の
# 付け方は命名規約で、一次文書の規定を埋めるものではない。
DECISION_PHRASE = re.compile(
    r'（\d{4}-\d{2}-\d{2}[^）]*(?:確定|決定|解消|解決)）'
    r'|\d{4}-\d{2}-\d{2} に(?:[^。]{0,40})?(?:確定|決定|決めた|判断した|定めた)'
    r'|統計解析責任者が(?:[^。]{0,20})?(?:決めた|判断した|確定)'
)
# 決定ではない行。命名規約と、一次文書の版の記録
NOT_DECISION = re.compile(r'^- 根拠：|表番号|E3 の 14')
# 台帳を引いている印。A/B/C の識別子、または台帳そのものへのリンク。
# 移設前からある16件は識別子を持たない（節名で引く）ため、後者も認める
IDENT = re.compile(r'(?<![A-Za-z0-9-])[ABC]-[0-9]{1,2}(?![0-9])|data-handling-decisions')
# 一次文書への言及。決定の形と同じ行に出たときだけ当てる。実装の履歴（いつ何を直したか）は
# 仕様書が持ってよいもので、台帳へ移す対象は一次文書との関係を決めたものに限る
PRIMARY = re.compile(r'SAP|PRT|研究計画書|プロトコル|プロトコール')
# 台帳そのものと、決定を持たない性質の文書は対象外
EXEMPT = {'data-handling-decisions.md'}


def entries():
    """台帳の各エントリの見出しと区分"""
    t = open(REG, encoding='utf-8').read()
    out, cur = [], None
    for line in t.split('\n'):
        line = line.rstrip('\r')
        if line.startswith('## '):
            cur = {'name': line[3:]}
            if cur['name'] not in FRAME:
                out.append(cur)
        elif cur is not None:
            for k, lab in (('区分', '- 区分：'), ('決め方', '- 決め方：'), ('CSR', '- CSR：')):
                if line.startswith(lab):
                    cur[k] = line[len(lab):]
    return out


def listed():
    """一覧の行"""
    t = open(REG, encoding='utf-8').read().split('\n')
    out, on = [], False
    for line in t:
        line = line.rstrip('\r')
        if line.startswith('## '):
            on = line[3:] == '一覧'
            continue
        if on and line.startswith('- '):
            out.append(line[2:])
    return out


def check_index(quiet):
    ents = entries()
    want = ['%s ── 区分 %s／決め方 %s／CSR %s'
            % (e['name'], e.get('区分', '?'), e.get('決め方', '?'), e.get('CSR', '?'))
            for e in ents]
    have = listed()
    bad = []
    if want != have:
        for x in want:
            if x not in have:
                bad.append('一覧に無い: ' + x)
        for x in have:
            if x not in want:
                bad.append('一覧にあって本文に無い: ' + x)
    miss = [e['name'] for e in ents if not all(k in e for k in ('区分', '決め方', 'CSR'))]
    for m in miss:
        bad.append('区分が揃っていない: ' + m)
    if not quiet:
        print('1. 一覧と本文 : エントリ %d 件 / 一覧 %d 行' % (len(ents), len(have)))
    return bad, ents


def check_spec(quiet):
    bad = []
    n_files = n_hits = 0
    for d in SCAN:
      for f in sorted(os.listdir(d)):
        if not f.endswith('.md') or f in EXEMPT:
            continue
        n_files += 1
        for i, line in enumerate(open(os.path.join(d, f), encoding='utf-8'), 1):
            line = line.rstrip('\n').rstrip('\r')
            if NOT_DECISION.search(line):
                continue
            if not (DECISION_PHRASE.search(line) and PRIMARY.search(line)):
                continue
            n_hits += 1
            if not IDENT.search(line):
                bad.append('決定を述べて識別子を引いていない: %s/%s:%d'
                           % (os.path.basename(d), f, i))
    if not quiet:
        print('2. 決定の記録 : %d ファイル / 決定の言い方 %d 箇所' % (n_files, n_hits))
    return bad


def check_purpose(ents, quiet):
    """台帳と analysis-purpose.csv の `reason` を突き合わせ、見直しの候補を並べる。

    この項目では落とさない。ARS の `reason` は解析がいつ計画されたかを表す語であり、
    実装が条文とずれたこと（逸脱）と同じ軸ではない。事前に規定された解析が、細部で
    条文とずれたまま実施されることはあり、その場合 `reason` は SPECIFIED IN SAP の
    ままが正しい。逆に、固定データを見てから解析を足した・定義を変えた場合は
    DATA DRIVEN になる。どちらであるかは統計解析責任者の判断なので、機械は候補を
    挙げるところまでにする。

    Output との対応は、エントリが `- 影響：` を持つならそれを使い、無ければ本文中の
    `Out-x` への言及で代える。言及は「この Output も同じ規則を参照する」という意味で
    書かれていることがあるため、対応としては粗い。
    """
    if not os.path.exists(PURPOSE):
        return ['analysis-purpose.csv が無い']
    reason = {}
    with open(PURPOSE, encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            if not r.get('analysis_id'):
                reason[r['output_id']] = r['reason']
    # 台帳の本文から Out-x への言及を拾う
    t = open(REG, encoding='utf-8').read()
    secs = t.split('\n## ')
    hard, soft = {}, {}
    for s in secs[1:]:
        name = s.split('\n')[0].rstrip('\r')
        if name in FRAME:
            continue
        kind = (re.search(r'- 区分：(\S+)', s) or [None, ''])[1]
        basis = (re.search(r'- 決め方：(\S+)', s) or [None, ''])[1]
        if kind == '逸脱':
            box = hard
        elif basis == '固定データ':
            box = soft
        else:
            continue
        m = re.search(r'- 影響：(.+)', s)
        outs = (set(re.findall(r'Out-[0-9]+(?:\.[0-9]+)*', m.group(1))) if m
                else set(re.findall(r'Out-[0-9]+(?:\.[0-9]+)*', s)))
        for o in outs:
            box.setdefault(o, []).append(name.split('（')[0])
    if quiet:
        return []
    print('3. reason の見直しの候補（この項目では落とさない）')
    for label, box in (('逸脱がある', hard), ('事後に決めた補完がある', soft)):
        rows = ['  %s（%s）… %s' % (o, reason[o], '／'.join(n)[:56])
                for o, n in sorted(box.items())
                if reason.get(o) and reason[o] != 'DATA DRIVEN' and (box is hard or o not in hard)]
        print('   %s Output %d 件のうち、事前規定のままのもの %d 件'
              % (label, len(box), len(rows)))
        for r in rows:
            print(r)
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()
    bad, ents = check_index(a.quiet)
    bad += check_spec(a.quiet)
    bad += check_purpose(ents, a.quiet)
    if bad:
        print()
        for b in bad:
            print('NG: ' + b)
        sys.exit('NG %d 件' % len(bad))
    print('OK')


if __name__ == '__main__':
    main()
