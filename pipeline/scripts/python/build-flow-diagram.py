# build-flow-diagram.py
#
# 登録から解析対象集団までの流れ（CONSORT 様式の症例の流れ図）を SVG で組み、HTML へ埋めて
# 出す。納品パッケージの 16_1_9_methods に入り、README の「解析対象集団と症例の流れ」から
# 開く。
#
# 数値はこのファイルに書かない。組み立てのたびに ARD（`datasets/r/ard/ard_cards_r.csv`）の
# Out-5.1 から読む。表 5.1（対象患者）・表 5.1.1（試験治療の完了・中止の内訳）・
# 表 5.1.2（試験の完了・中止の内訳）が読んでいるのと同じ行なので、図と表が食い違わない。
# 集団の定義と期待する例数は `docs/validation/acceptance/analysis-set-condition.csv` が持ち、除外の件数は
# 段と段の差として ARD から出る。除外の理由（文）は `docs/records/analysis-population-derivation.md`
# が正本で、ここには要約した一句だけを置く。図が前提にする整合（転帰の分母が FAS・SAF と
# 同数であること、理由別の件数の合計が分母と一致すること）は組み立てのたびに確かめ、
# 合わなければ図を描かずに止める。
#
# 表示文言は `docs/metadata/label-catalog.csv` の `kind=flow` が持つ（日本語版・英語版）。
# 図の中に文字列を書かないので、言い回しを直すときはカタログを直す。キーが欠けたら
# 空欄を描かずに止める。
#
#   python scripts/build-flow-diagram.py                  ... Box の output/spec/ へ書く
#   python scripts/build-flow-diagram.py --out-dir <dir>  ... 出力先を変える（パッケージ生成が使う）
#   python scripts/build-flow-diagram.py --quiet          ... 1行だけ報告する
import sys, os, csv, html, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META = os.path.join(REPO, 'docs', 'metadata')
NL = chr(10)

# 出力の名前。README とパッケージ生成がこの名前を指す
NAME = {'ja': 'subject-flow.html', 'en': 'subject-flow-en.html'}

# 同じ数値を持つ図表（14_tlf に入る）。表番号は tlf-index.csv の宣言と同じもので、
# 題名は label-catalog.csv の title 行から引く
TABLES = ['T_5_1', 'T_5_1_1', 'T_5_1_2']

# 解析対象集団の判定（16_1_9_methods に build-spec-html.py が入れる HTML）
DERIVATION = 'analysis-population-derivation.html'

# ARD の Out-5.1 が段の例数を持つときの水準名。集団の識別子は
# docs/validation/acceptance/analysis-set-condition.csv の id と対応する
LV_ALL, LV_FAS, LV_SAF, LV_PPS = 'ALLENR', 'FAS', 'SAF', 'PPS'
LV_HSCT, LV_PN = 'ALLHSCT', 'PNINTRO'


# --- 読む ---------------------------------------------------------------------------------

def read_labels(lang):
    """表示文言。kind=flow の行だけを引く。無いキーを引いたらその場で止める"""
    d = {}
    with open(os.path.join(META, 'label-catalog.csv'), encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            if r['kind'] == 'flow':
                d[r['key']] = (r['label_ja'] if lang == 'ja' else r['label_en']).strip()

    def get(key):
        v = d.get(key)
        if not v:
            raise SystemExit(f'label-catalog.csv に kind=flow の {key}（{lang}）が無い')
        return v
    return get


def read_titles():
    """図表の題名。kind=title の行を言語ごとに持つ"""
    out = {}
    with open(os.path.join(META, 'label-catalog.csv'), encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            if r['kind'] == 'title':
                out[r['key']] = {'ja': r['label_ja'].strip(), 'en': r['label_en'].strip()}
    return out


def read_ard(box):
    """ARD を読む。納品する図表は R 系なので R 系の1本だけを見る"""
    p = os.path.join(box, 'datasets', 'r', 'ard', 'ard_cards_r.csv')
    if not os.path.exists(p):
        raise SystemExit(f'ARD がない: {p}')
    with open(p, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f)), p


def num(r):
    try:
        return int(float(r['stat_num']))
    except (TypeError, ValueError):
        return None


def stage_counts(rows):
    """各段の例数。Out-5.1 の DISPOSITION 行を水準名で引く"""
    out = {}
    for r in rows:
        if (r['output_id'] == 'Out-5.1' and r['variable'] == 'DISPOSITION'
                and r['stat_name'] == 'n'):
            n = num(r)
            if n is not None:
                out[r['variable_level']] = n
    return out


def disposition(rows, spid):
    """完了・中止の内訳。DSSPID が TXEND（試験治療）・OBSEND（試験）の DSTERM 別の件数と分母"""
    cnt, den = {}, None
    for r in rows:
        if not (r['output_id'] == 'Out-5.1' and r['variable'] == 'DSTERM'
                and r['group1'] == 'DSSPID' and r['group1_level'] == spid):
            continue
        n = num(r)
        if n is None:
            continue
        if r['stat_name'] == 'n':
            cnt[r['variable_level']] = n
        elif r['stat_name'] == 'N' and den is None:
            den = n
    return cnt, den


def need(d, key, what):
    if key not in d:
        raise SystemExit(f'ARD の Out-5.1 に {what}（{key}）が無い')
    return d[key]


def verify(cnt, tx, tx_den, ob, ob_den):
    """図が前提にしていることを ARD の値で確かめる。合わなければ描かずに止める。

    転帰の段は、分母を FAS・SAF の例数として描き、中止をその分母と完了の差として出す。
    分母が FAS・SAF と食い違ったり、理由別の件数の合計が分母に足りなかったりすると、
    図の中だけで足し算の合わない数が並ぶ。FAS と SAF が同一集団であることは
    `docs/validation/acceptance/analysis-set-condition.csv` の宣言でもある。
    """
    n_fas = need(cnt, LV_FAS, 'FAS')
    n_saf = need(cnt, LV_SAF, 'SAF')
    if n_fas != n_saf:
        raise SystemExit(f'FAS {n_fas} と SAF {n_saf} が同数でない')
    for what, cnts, den in (('試験治療の転帰（DSSPID=TXEND）', tx, tx_den),
                            ('試験の転帰（DSSPID=OBSEND）', ob, ob_den)):
        if den != n_fas:
            raise SystemExit(f'{what}の分母 {den} が FAS・SAF の {n_fas} と合わない')
        if 'COMPLETED' not in cnts:
            raise SystemExit(f'{what}に完了（COMPLETED）が無い')
        s = sum(cnts.values())
        if s != den:
            raise SystemExit(f'{what}の理由別の件数の合計 {s} が分母 {den} と合わない')


# --- 文字の幅と折り返し ---------------------------------------------------------------------
#
# SVG は文字を測れないので、和文を1文字ぶん・欧文を 0.55 文字ぶんとして概算する。箱の幅は
# 呼ぶ側が決め、収まらない行だけを折る。

def char_w(ch, size):
    return size * (1.0 if ord(ch) > 0x2E7F else 0.55)


def text_w(s, size):
    return sum(char_w(c, size) for c in s)


def tokens(s):
    """折り返しの単位。和文は1文字、欧文は語をひとまとまりにする"""
    out, buf = [], ''
    for ch in s:
        if ch == ' ':
            if buf:
                out.append(buf)
                buf = ''
        elif ord(ch) > 0x2E7F:
            if buf:
                out.append(buf)
                buf = ''
            out.append(ch)
        else:
            buf += ch
    if buf:
        out.append(buf)
    return out


def wrap(s, maxpx, size):
    lines, cur = [], ''
    for t in tokens(s):
        sep = ' ' if (cur and t[:1].isascii() and cur[-1:].isascii()) else ''
        cand = cur + sep + t
        if cur and text_w(cand, size) > maxpx:
            lines.append(cur)
            cur = t
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


# --- 図を組む -----------------------------------------------------------------------------
#
# 色は使わない。線と文字だけで、箱は白地に細い枠、矢印は同じ太さの直線と小さな三角。

W = 940                 # 画布の幅
MARGIN = 24
INK = '#1a1a1a'
FS = 13                 # 箱の中の文字
FS_SMALL = 12           # 内訳の行
FS_STAGE = 12           # 段の見出し
LH = 17                 # 行の高さ
PAD = 9                 # 箱の内側の余白
GAP = 26                # 箱と箱の縦の間


def esc(s):
    return html.escape(str(s), quote=False)


class Canvas:
    """上から下へ積むだけの画布。y を持ち回り、最後に高さを決める"""

    def __init__(self):
        self.el = []
        self.y = MARGIN

    def add(self, s):
        self.el.append(s)

    def text(self, x, y, s, size=FS, anchor='middle', weight=None):
        w = f' font-weight="{weight}"' if weight else ''
        self.add(f'<text x="{x:.0f}" y="{y:.0f}" font-size="{size}" '
                 f'text-anchor="{anchor}"{w}>{esc(s)}</text>')

    def box(self, cx, y, w, lines, size=FS, align='middle'):
        """中心 cx・上端 y の箱。lines は折り返し済みの行。返すのは高さ"""
        h = PAD * 2 + LH * len(lines)
        x = cx - w / 2
        self.add(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" '
                 f'fill="#ffffff" stroke="{INK}" stroke-width="1"/>')
        tx = cx if align == 'middle' else x + PAD
        for i, s in enumerate(lines):
            self.text(tx, y + PAD + LH * i + 13, s, size=size, anchor=align)
        return h

    def line(self, x1, y1, x2, y2, arrow=False):
        a = f' marker-end="url(#arw)"' if arrow else ''
        self.add(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
                 f'stroke="{INK}" stroke-width="1"{a}/>')

    def stage(self, label):
        """段の見出しと区切りの罫"""
        self.text(MARGIN, self.y + 12, label, size=FS_STAGE, anchor='start', weight='600')
        self.line(MARGIN, self.y + 19, W - MARGIN, self.y + 19)
        self.y += 34

    def svg(self):
        h = self.y + MARGIN
        head = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h:.0f}" '
                f'width="{W}" height="{h:.0f}" role="img">',
                '<defs><marker id="arw" viewBox="0 0 10 10" refX="9" refY="5" '
                'markerWidth="7" markerHeight="7" orient="auto-start-reverse">',
                f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{INK}"/></marker></defs>',
                '<style>text { font-family: "Hiragino Sans","Yu Gothic UI",Meiryo,'
                'Arial,sans-serif; fill: ' + INK + '; }</style>']
        return NL.join(head + self.el + ['</svg>'])


def build_svg(lang, L, cnt, tx, tx_den, ob, ob_den):
    """症例の流れ図。L は文言、cnt は各段の例数、tx・ob は完了と中止の内訳"""
    c = Canvas()

    def n(x):
        return L('flow.count').replace('{n}', str(x))

    def joined(label, x):
        """見出しと例数を1行にする。空きの幅は言語で決める（和文は全角）"""
        return label + ('　' if lang == 'ja' else ' ') + n(x)

    # 主たる流れの列と、右へ出す除外の列
    main_cx, main_w = 250, 340
    side_cx, side_w = 700, 400

    n_all = need(cnt, LV_ALL, '全登録例')
    n_fas = need(cnt, LV_FAS, 'FAS')
    n_pps = need(cnt, LV_PPS, 'PPS')

    # --- 登録と解析対象集団 ---
    c.stage(L('flow.stage.sets'))
    c.y += c.box(main_cx, c.y, main_w, [joined(L('flow.enrolled'), n_all)])

    def branch(excl_label, excl_reason, excl_n, next_lines):
        """いまの箱から下へ1段進み、その途中で右へ除外を出す"""
        y0 = c.y
        mid = y0 + GAP
        side = ([joined(excl_label, excl_n)]
                + wrap(excl_reason, side_w - PAD * 2, FS))
        sy = mid - (PAD * 2 + LH * len(side)) / 2
        sh = c.box(side_cx, sy, side_w, side)
        c.line(main_cx, mid, side_cx - side_w / 2, mid, arrow=True)
        c.line(main_cx, y0, main_cx, y0 + GAP * 2, arrow=True)
        c.y = y0 + GAP * 2
        h = c.box(main_cx, c.y, main_w, next_lines)
        c.y = max(c.y + h, sy + sh)

    # FAS と SAF は同一集団なので1つの箱に置く。同数であることは verify が確かめている
    branch(L('flow.excluded.sets'), L('flow.excluded.sets.reason'), n_all - n_fas,
           [joined(L('flow.fassaf'), n_fas)]
           + wrap(L('flow.fassaf.note'), main_w - PAD * 2, FS_SMALL))
    branch(L('flow.excluded.pps'), L('flow.excluded.pps.reason'), n_fas - n_pps,
           [joined(L('flow.pps'), n_pps)]
           + wrap(L('flow.pps.note'), main_w - PAD * 2, FS_SMALL))
    c.y += 14

    # --- 試験治療の転帰・試験の転帰 ---
    for stage_key, cnts, den in ((L('flow.stage.txend'), tx, tx_den),
                                 (L('flow.stage.obsend'), ob, ob_den)):
        c.stage(stage_key)
        done = cnts['COMPLETED']
        rest = sorted(((k, v) for k, v in cnts.items() if k != 'COMPLETED'),
                      key=lambda kv: (-kv[1], kv[0]))
        top = c.y
        h = c.box(W / 2, top, 300, [joined(L('flow.fassaf'), den)])
        c.y = top + h
        # 分岐。完了は左、中止は右
        lx, rx = 250, 690
        c.line(W / 2, c.y, W / 2, c.y + 14)
        c.line(lx, c.y + 14, rx, c.y + 14)
        c.line(lx, c.y + 14, lx, c.y + GAP, arrow=True)
        c.line(rx, c.y + 14, rx, c.y + GAP, arrow=True)
        c.y += GAP
        hl = c.box(lx, c.y, 300, [joined(L('flow.completed'), done)])
        hr = c.box(rx, c.y, 300, [joined(L('flow.discontinued'), den - done)])
        c.y += max(hl, hr)
        # 中止の内訳
        c.line(rx, c.y, rx, c.y + GAP, arrow=True)
        c.y += GAP
        lines = [L('flow.reasons')] + [joined(k, v) for k, v in rest]
        rw = max(360, min(560, max(text_w(s, FS_SMALL) for s in lines) + PAD * 2 + 10))
        h = c.box(rx, c.y, rw, lines, size=FS_SMALL, align='start')
        c.y += h + 14

    # --- FAS の部分集合 ---
    c.stage(L('flow.stage.subsets'))
    top = c.y
    h = c.box(W / 2, top, 300, [joined(L('flow.fassaf'), n_fas)])
    c.y = top + h
    lx, rx = 250, 690
    c.line(W / 2, c.y, W / 2, c.y + 14)
    c.line(lx, c.y + 14, rx, c.y + 14)
    c.line(lx, c.y + 14, lx, c.y + GAP, arrow=True)
    c.line(rx, c.y + 14, rx, c.y + GAP, arrow=True)
    c.y += GAP
    hl = c.box(lx, c.y, 340, wrap(joined(L('flow.hsct'), need(cnt, LV_HSCT, '全移植例')),
                                  340 - PAD * 2, FS))
    hr = c.box(rx, c.y, 340, wrap(joined(L('flow.pn'), need(cnt, LV_PN, 'PN導入例')),
                                  340 - PAD * 2, FS))
    c.y += max(hl, hr)
    return c.svg()


# --- HTML --------------------------------------------------------------------------------

PAGE = '''<!DOCTYPE html>
<html lang="__LANG__"><head><meta charset="utf-8"><title>__TITLE__</title>
<style>
body{font-family:"Hiragino Sans","Yu Gothic UI",Meiryo,Arial,sans-serif;margin:24px auto;
max-width:1000px;color:#1a1a1a;font-size:14px;line-height:1.6}
h1{font-size:1.1rem}p.note{color:#555;font-size:.86rem;margin:10px 0 0}
ul{margin:6px 0;padding-left:22px}li{margin:2px 0}a{color:#004a95}
div.nav{margin-top:16px;padding-top:8px;border-top:1px solid #e2e2e2;font-size:.8rem}
div.nav p{margin:2px 0}
svg{max-width:100%;height:auto}
</style></head><body>
<h1>__TITLE__</h1>
__SVG__
<p class="note">__SOURCE__</p>
<p class="note">__TABLESLBL__</p>
<ul>
__TABLES__</ul>
<div class="nav">
<p><a href="__DERIV__">__DERIVLBL__</a></p>
<p><a href="__OTHER__">__OTHERLBL__</a></p>
<p><a href="../README.html">__BACK__</a></p>
</div>
</body></html>
'''


def build_page(lang, L, svg, titles):
    li = []
    for t in TABLES:
        ttl = titles.get(t, {}).get(lang) or t
        li.append(f'<li><a href="../14_tlf/{lang}/{t}.html">{esc(ttl)}</a> <code>{t}</code></li>')
    other = NAME['en'] if lang == 'ja' else NAME['ja']
    return (PAGE.replace('__LANG__', lang)
            .replace('__TITLE__', esc(L('flow.title')))
            .replace('__SVG__', svg)
            .replace('__SOURCE__', esc(L('flow.source')))
            .replace('__TABLESLBL__', esc(L('flow.tables')))
            .replace('__TABLES__', NL.join(li) + NL)
            .replace('__DERIV__', DERIVATION)
            .replace('__DERIVLBL__', esc(L('flow.derivation')))
            .replace('__OTHER__', other)
            .replace('__OTHERLBL__', esc(L('flow.otherlang')))
            .replace('__BACK__', esc(L('flow.back'))))


def write_flow(outdir, box, quiet=False):
    """症例の流れ図を outdir へ書く。書いたファイル数を返す"""
    rows, src = read_ard(box)
    cnt = stage_counts(rows)
    tx, tx_den = disposition(rows, 'TXEND')
    ob, ob_den = disposition(rows, 'OBSEND')
    if not tx or tx_den is None:
        raise SystemExit('ARD の Out-5.1 に試験治療の完了・中止の内訳（DSSPID=TXEND）が無い')
    if not ob or ob_den is None:
        raise SystemExit('ARD の Out-5.1 に試験の完了・中止の内訳（DSSPID=OBSEND）が無い')
    verify(cnt, tx, tx_den, ob, ob_den)
    titles = read_titles()
    os.makedirs(outdir, exist_ok=True)
    n = 0
    for lang in ('ja', 'en'):
        L = read_labels(lang)
        page = build_page(lang, L, build_svg(lang, L, cnt, tx, tx_den, ob, ob_den), titles)
        with open(os.path.join(outdir, NAME[lang]), 'w', encoding='utf-8', newline=NL) as f:
            f.write(page)
        n += 1
    if not quiet:
        print(f'  読んだ ARD: {src}')
        print(f'  登録 {cnt.get(LV_ALL)} / FAS {cnt.get(LV_FAS)} / SAF {cnt.get(LV_SAF)} / '
              f'PPS {cnt.get(LV_PPS)} / 移植 {cnt.get(LV_HSCT)} / PN {cnt.get(LV_PN)}')
        print(f'  試験治療の転帰 {len(tx)} 区分（分母 {tx_den}）/ '
              f'試験の転帰 {len(ob)} 区分（分母 {ob_den}）')
    print(f'症例の流れ図: {n} ファイル -> {outdir}')
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()
    box = boxpath.trial_dir()
    outdir = a.out_dir or os.path.join(box, 'output', 'spec')
    write_flow(outdir, box, a.quiet)


if __name__ == '__main__':
    main()
