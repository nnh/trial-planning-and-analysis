# check-review-ledger.py
#
# 独立レビューの台帳（docs/validation/records/*-ledger.md）で、見出し行の
# 状態欄が各項の記録と食い違っていないかを見る。
#
# なぜ要るか。台帳の状態欄は着手前に作業の波（第0波から第5波）や「判断待ち」を置き、
# 対応が済んだ時点で日付つきの完了・決着へ改める約束になっている。改める操作は各項の
# 記録を書く操作とは別なので、記録だけ書いて状態欄を置き去りにしても何も起こらない。
# 実際に第2回台帳では221件すべての結果が埋まったあとも153件が着手前の値のまま残り、
# 台帳が件数の正本として使えなくなっていた。そのずれを根拠に、別の文書が「C2-115 は
# 未決である」という誤った前提を書いた（2026-09-06 に統計解析責任者が是正を指示）。
#
# 見るもの。
#   1. 状態が着手前の値（第N波）なのに、対応の記録が書かれている項
#   2. 状態が「判断待ち」なのに、記録の冒頭が完了・決着・対応不要を述べている項
#   3. 状態が完了系（完了・決着・対応不要）なのに、対応の記録が1行も無い項
#   4. 状態欄の値が語彙（日付＋完了／決着／対応不要、判断待ち、第N波）の外にある項
#   5. 節の頭の件数（「N件。判断 X件、機械 Y件。」）が実際の項目数と合うか
#
# 見ないもの。記録の中身が正しいか（書かれた対応が本当に済んでいるか）は人が読む。
# ここが見るのは、記録の有無と状態欄の値が互いに矛盾していないことだけである。
#
# 記録の行は台帳によって鍵が違う。第2回は `- 結果：`、第3回は落とした項が `- 再検証：`、
# 対応した項の一部が `- 対応：` を持つ。どれか1つでもあれば記録があるものとして扱う。
# 「結果が無ければ未対応」と決め打つと、第3回の C3-103・C3-104・C3-115 が誤って挙がる。
#
# 材料が無いときは何が無いかを述べて非0で終える。台帳はリポジトリの中にあり外部の道具に
# 依存しないので、飛ばす口（--allow-skip）は付けない。ファイルが無い・1件も項目を読めない
# のは環境の不足ではなく、台帳か検査の側の異常である。
#
#   python scripts/check-review-ledger.py                ... 台帳の置き場にある *-ledger.md すべて
#   python scripts/check-review-ledger.py <path.md> ...  ... 任意の台帳
#
# 終了コード 0 ERROR 無し / 1 ERROR あり
import sys, os, re, glob, collections

sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_DIR = os.path.join(REPO, 'docs', 'validation', 'records')
# 既定の対象は台帳の置き場にある *-ledger.md すべて。台帳の名前（何回目の・誰のレビューか）は
# 試験ごとに変わるので、ここへ名前を列挙しない。列挙すると、新しい台帳を足した回だけ
# 検査の対象から漏れ、漏れたことは何も起こらないので気づけない。
# 1件も無ければ main が何が無いかを述べて非0で終える。


def default_ledgers():
    return sorted(glob.glob(os.path.join(LEDGER_DIR, '*-ledger.md')))


# 見出し行は `- <番号>　<節>　<重要度>　<分類>　<状態>[　<依存>]` の全角空白区切り。
# 依存欄は第2回だけが持つので、位置で取れるのは状態欄までである
HDR = re.compile(r'^- (C\d+-\d+)\u3000(.+)$')
SUB = re.compile(r'^  - ([^\uff1a]{1,8})\uff1a(.*)$')
I_CLASS, I_STATE = 2, 3

DONE = re.compile(r'^20\d\d-\d\d-\d\d (完了|決着|対応不要)$')
WAVE = re.compile(r'^第\d+波$')
PENDING = '判断待ち'
# 記録の鍵。対応の内容を述べる行を指す（指摘・計画・確認・判断は対応の記録ではない）
RECORD_KEYS = ('結果', '対応', '再検証')
# 記録の冒頭が完了を宣言しているかを見る範囲。「2026-08-30 に判断として決着。」のように
# 日付と語の間に語句が挟まる書き方があるので、語の一致だけでなく冒頭の窓で見る
DECLARE_HEAD = 30
DECLARE = ('完了', '決着', '対応不要')
COUNT = re.compile(r'^(\d+)件。(.+)。$')
COUNT_ITEM = re.compile(r'(判断|機械|対応不要|目視)\s*(\d+)件')
# 分類を機械から判断へ改めた項。件数の上では判断として数える（第3回台帳の書き方）
CLASS_ALIAS = {'機械→判断': '判断'}


def parse(path):
    """台帳を節と項目へ分解する。"""
    lines = open(path, encoding='utf-8').read().split('\n')
    sections, items = [], []
    cur_sec, cur_item = None, None
    for i, ln in enumerate(lines):
        if ln.startswith('## '):
            cur_sec = {'name': ln[3:].strip(), 'line': i + 1, 'count': None,
                       'items': []}
            sections.append(cur_sec)
            cur_item = None
            continue
        m = HDR.match(ln)
        if m:
            f = m.group(2).split('\u3000')
            cur_item = {'id': m.group(1), 'line': i + 1, 'fields': f,
                        'sub': collections.OrderedDict()}
            items.append(cur_item)
            if cur_sec is not None:
                cur_sec['items'].append(cur_item)
            continue
        s = SUB.match(ln)
        if s and cur_item is not None:
            cur_item['sub'].setdefault(s.group(1), s.group(2))
            continue
        if ln.startswith('- ') or (ln and not ln.startswith(' ')):
            cur_item = None
        if cur_sec is not None and cur_sec['count'] is None and not cur_sec['items']:
            c = COUNT.match(ln)
            if c:
                cur_sec['count'] = {'line': i + 1, 'total': int(c.group(1)),
                                    'by': {k: int(v)
                                           for k, v in COUNT_ITEM.findall(c.group(2))}}
    return items, sections


def klass(it):
    v = it['fields'][I_CLASS] if len(it['fields']) > I_CLASS else ''
    return CLASS_ALIAS.get(v, v)


def check(path, err, warn):
    items, sections = parse(path)
    name = os.path.basename(path)
    if not items:
        err.append(f'{name}: 項目を1件も読めなかった'
                   '（見出し行の形が変わったか、台帳ではない）')
        return
    n_done = n_open = 0
    for it in items:
        where = f'{name}:{it["line"]} {it["id"]}'
        if len(it['fields']) <= I_STATE:
            err.append(f'{where}: 見出し行の欄が足りない（状態欄が読めない）')
            continue
        state = it['fields'][I_STATE]
        rec_key = next((k for k in RECORD_KEYS
                        if it['sub'].get(k, '').strip()), None)
        rec = it['sub'][rec_key] if rec_key else ''

        if DONE.match(state):
            n_done += 1
            if not rec_key:
                err.append(f'{where}: 状態が「{state}」なのに対応の記録が無い'
                           f'（{"・".join(RECORD_KEYS)} のいずれかの行を書く）')
        elif WAVE.match(state):
            n_open += 1
            if rec_key:
                err.append(f'{where}: 状態が着手前の波「{state}」のまま'
                           f'{rec_key}が書かれている'
                           f'（済んだなら日付つきの完了・決着へ、'
                           f'決まっていないなら判断待ちへ改める）')
        elif state == PENDING:
            n_open += 1
            if rec_key and any(w in rec[:DECLARE_HEAD] for w in DECLARE):
                err.append(f'{where}: 状態が「{PENDING}」なのに'
                           f'{rec_key}が「{rec[:DECLARE_HEAD].strip()}」と'
                           '決着を述べている')
        else:
            err.append(f'{where}: 状態欄の値が語彙の外にある（「{state}」）。'
                       '日付つきの完了・決着・対応不要、判断待ち、第N波のいずれかにする')

    for sec in sections:
        c = sec['count']
        if c is None:
            continue
        act = collections.Counter(klass(x) for x in sec['items'])
        where = f'{name}:{c["line"]} {sec["name"]}'
        if c['total'] != len(sec['items']):
            err.append(f'{where}: 節の頭が {c["total"]}件 と書いているが、'
                       f'実際の項目は {len(sec["items"])}件')
        for k, v in sorted(c['by'].items()):
            if act.get(k, 0) != v:
                err.append(f'{where}: 節の頭が {k} {v}件 と書いているが、'
                           f'実際は {act.get(k, 0)}件')

    print(f'{name}: {len(items)} 件（対応済み {n_done} / 未了 {n_open}）'
          f' 節 {len(sections)}')


def main(argv):
    paths = [os.path.abspath(a) for a in argv] or default_ledgers()
    if not paths:
        print('材料が無い: 台帳が1件も無い（' + LEDGER_DIR + ' の *-ledger.md）')
        print('台帳を1件も読んでいない。'
              '検査の対象が消えたのか、道を間違えたのかを先に確かめる。')
        return 1
    lack = [p for p in paths if not os.path.exists(p)]
    if lack:
        for p in lack:
            print('材料が無い: 台帳が見つからない（' + p + '）')
        print('台帳を1件も読んでいない。'
              '検査の対象が消えたのか、道を間違えたのかを先に確かめる。')
        return 1

    err, warn = [], []
    for p in paths:
        check(p, err, warn)
    for w in warn:
        print('WARN:', w)
    for e in err:
        print('ERROR:', e)
    print(f'ERROR {len(err)} 件 / WARN {len(warn)} 件')
    return 1 if err else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
