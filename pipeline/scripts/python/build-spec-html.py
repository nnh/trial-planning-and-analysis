# build-spec-html.py
#
# docs/ の仕様書（md）を、節ごとに id を振った HTML へ変換する。
# 追跡索引（traceability.html）の「仕様書」欄から該当節へ直接飛べるようにするためのもので、
# 正本はあくまで md である（CLAUDE.md「文書の正本」）。HTML は配布用の派生物なので、
# 内容を直すときは md を直してこれを回し直す。
#
#   python scripts/build-spec-html.py                  ... Box の output/spec/ へ書く
#   python scripts/build-spec-html.py --out-dir <dir>  ... 出力先を変える（パッケージ生成が使う）
#   python scripts/build-spec-html.py --quiet          ... 1行だけ報告する
#
# 節の id は `s-<節番号>` で、節番号は見出しの先頭にある番号（`3.7`・`2.2.1`・`Out-5.2.1`）を
# そのまま使う。docs/variable-map.csv の spec_ref（`sdtm-spec.md §3.7`）と ARD の output_id
# （`Out-5.2.1`）から機械的に組める形にしてあり、索引側は生成した HTML の id を読んで
# 実在を確かめてからリンクを出す。
#
# 変換は外部ライブラリに依存しない。対象の md が使う記法（見出し・段落・箇条書き・番号リスト・
# コード柵・表・インラインコード・太字・リンク・水平線）だけを実装している。pandoc に頼らない
# のは、SAS を回す Windows 機でもパッケージを作り直せるようにするため。
import sys, os, re, glob, html, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 変換の対象。PI パッケージの 16_1_9_methods に入れる仕様と、変数の spec_ref が指すものを揃える
FILES = ['sdtm-spec.md', 'adam-spec.md', 'ars-spec-index.md',
         'analysis-population-derivation.md', 'ard-double-coding-spec.md',
         'engraftment-external-data-spec.md', 'abl1-mutation-external-data-spec.md',
         'r-pipeline-spec.md', 'label-and-traceability-design.md',
         'data-handling-decisions.md']

CSS = """
 :root { --line:#e2e2e2; --accent:#004a95; --muted:#767676; --hi:#eef4fb; }
 * { box-sizing:border-box; }
 body { font-family:"Hiragino Sans","Yu Gothic UI",-apple-system,"Segoe UI",Meiryo,sans-serif;
        margin:0; color:#1a1a1a; background:#fff; font-size:15px; line-height:1.75; }
 header { padding:14px 20px 12px; border-bottom:1px solid var(--line); }
 header .in { max-width:860px; margin:0 auto; display:flex; align-items:baseline; gap:14px;
              flex-wrap:wrap; }
 header .doc { font-size:.95rem; font-weight:600; }
 header .back { margin-left:auto; font-size:.78rem; }
 main { max-width:860px; margin:0 auto; padding:8px 20px 80px; }
 h1 { font-size:1.25rem; margin:18px 0 10px; }
 h2 { font-size:1.05rem; margin:30px 0 8px; padding-top:6px; border-top:1px solid var(--line); }
 h3 { font-size:.95rem; margin:22px 0 6px; }
 h4, h5, h6 { font-size:.9rem; margin:18px 0 6px; }
 h2 a.p, h3 a.p, h4 a.p { font-size:.7rem; color:var(--muted); text-decoration:none;
                          margin-left:8px; visibility:hidden; }
 h2:hover a.p, h3:hover a.p, h4:hover a.p { visibility:visible; }
 :target { background:#fffdf3; }
 p, li { margin:6px 0; }
 ul, ol { margin:6px 0; padding-left:24px; }
 a { color:var(--accent); }
 code { background:#eef0f2; padding:1px 5px; border-radius:4px; font-size:.88em;
        font-family:ui-monospace,Menlo,Consolas,monospace; }
 pre { background:#f6f8fa; border:1px solid var(--line); border-radius:6px; padding:10px 12px;
       overflow-x:auto; }
 pre code { background:none; padding:0; font-size:.82rem; }
 table { border-collapse:collapse; margin:10px 0; font-size:.86rem; }
 th, td { border:1px solid var(--line); padding:4px 9px; text-align:left; }
 th { background:#f1f3f5; }
 hr { border:none; border-top:1px solid var(--line); margin:24px 0; }
 nav.toc { background:#fafbfc; border:1px solid var(--line); border-radius:8px;
           padding:10px 16px; margin:16px 0 8px; font-size:.86rem; }
 nav.toc .t { font-size:.74rem; color:var(--muted); }
 nav.toc ul { list-style:none; padding-left:0; margin:4px 0 0; }
 nav.toc ul ul { padding-left:18px; }
 nav.toc li { margin:1px 0; }
 footer { max-width:860px; margin:24px auto 0; padding:12px 20px 0;
          border-top:1px solid var(--line); font-size:.78rem; color:var(--muted); }
"""


def sec_id(sec):
    """節番号から id を作る。索引側（build-traceability.py）と同じ規則を使う"""
    return 's-' + sec


def inline(t, links):
    """段落の中身。`code` を先に取り置いてから残りを処理する（中身を触らないため）"""
    keep = []

    def hold(m):
        keep.append('<code>' + html.escape(m.group(1)) + '</code>')
        return '\x00%d\x00' % (len(keep) - 1)

    t = re.sub(r'`([^`]+)`', hold, t)
    t = html.escape(t)
    t = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', t)
    t = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', lambda m: links(m.group(1), m.group(2)), t)
    return re.sub(r'\x00(\d+)\x00', lambda m: keep[int(m.group(1))], t)


def convert(md, links):
    """md を本文の HTML と目次の項目へ変換する"""
    lines = md.split('\n')
    out, toc, ids = [], [], {}
    i = 0
    while i < len(lines):
        ln = lines[i]

        if ln.startswith('```'):                       # コード柵
            i += 1
            buf = []
            while i < len(lines) and not lines[i].startswith('```'):
                buf.append(html.escape(lines[i]))
                i += 1
            i += 1
            out.append('<pre><code>' + '\n'.join(buf) + '</code></pre>')
            continue

        m = re.match(r'^(#{1,6})\s+(.*)$', ln)
        if m:                                          # 見出し。節番号があれば id にする
            lv, txt = len(m.group(1)), m.group(2).strip()
            num = re.match(r'^(Out-[\d.]+|\d+(?:\.\d+)*)\.?\s+(.+)$', txt)
            key = sec_id(num.group(1)) if num else 'h%d' % (len(ids) + 1)
            if key in ids:                             # 同じ節番号が2度出たら連番で分ける
                ids[key] += 1
                key = '%s-%d' % (key, ids[key])
            else:
                ids[key] = 1
            body = inline(txt, links)
            out.append('<h%d id="%s">%s<a class="p" href="#%s">#</a></h%d>'
                       % (lv, key, body, key, lv))
            if 2 <= lv <= 3:
                toc.append((lv, key, txt))
            i += 1
            continue

        if ln.startswith('|'):                         # 表。2行目が区切りのときだけ表にする
            blk = []
            while i < len(lines) and lines[i].startswith('|'):
                blk.append(lines[i])
                i += 1
            cells = [[c.strip() for c in r.strip().strip('|').split('|')] for r in blk]
            sep = len(cells) > 1 and all(re.fullmatch(r':?-{2,}:?', c) for c in cells[1])
            rows = ['<tr>' + ''.join('<%s>%s</%s>' % (tag, inline(c, links), tag)
                                     for c in r) + '</tr>'
                    for n, r in enumerate(cells) if not (sep and n == 1)
                    for tag in ['th' if sep and n == 0 else 'td']]
            out.append('<table>' + ''.join(rows) + '</table>')
            continue

        if re.match(r'^\s*([-*+]|\d+\.)\s+', ln):      # 箇条書き・番号リスト（入れ子を許す）
            blk = []
            while i < len(lines) and (re.match(r'^\s*([-*+]|\d+\.)\s+', lines[i]) or
                                      (lines[i].startswith('  ') and lines[i].strip())):
                blk.append(lines[i])
                i += 1
            out.append(list_html(blk, links))
            continue

        if re.fullmatch(r'\s*-{3,}\s*', ln):
            out.append('<hr>')
            i += 1
            continue

        if not ln.strip():                             # 空行は段落の区切り
            i += 1
            continue

        buf = []                                       # 段落（続く行はつなげる）
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(('#', '|', '```')) \
                and not re.match(r'^\s*([-*+]|\d+\.)\s+', lines[i]):
            buf.append(lines[i].strip())
            i += 1
        out.append('<p>' + inline(''.join(buf), links) + '</p>')
    return '\n'.join(out), toc


def list_html(blk, links):
    """リストを入れ子ごと組む。インデント2文字を1段として扱う"""
    items = []                     # (深さ, 番号付きか, 中身)
    for ln in blk:
        m = re.match(r'^(\s*)([-*+]|\d+\.)\s+(.*)$', ln)
        if m:
            items.append([len(m.group(1)) // 2, m.group(2) not in '-*+', m.group(3)])
        elif items:                # 続きの行は前の項目へつなげる
            items[-1][2] += ln.strip()

    def build(pos, depth):
        tag = 'ol' if items[pos][1] else 'ul'
        h = '<' + tag + '>'
        while pos < len(items):
            d, _, txt = items[pos]
            if d < depth:
                break
            if d > depth:
                sub, pos = build(pos, d)
                h += sub
                continue
            h += '<li>' + inline(txt, links) + '</li>'
            pos += 1
        return h + '</' + tag + '>', pos

    return build(0, items[0][0])[0] if items else ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir')
    ap.add_argument('--back', default='../traceability.html',
                    help='各ページに出す索引への戻り道（空文字で出さない）')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    box = boxpath.trial_dir(required=False)
    outdir = args.out_dir or (os.path.join(box, 'output', 'spec') if box else
                              os.path.join(REPO, 'spec'))
    os.makedirs(outdir, exist_ok=True)

    have = [f for f in FILES if os.path.exists(os.path.join(REPO, 'docs', f))]
    names = {f: os.path.splitext(f)[0] + '.html' for f in have}

    def links_for(src):
        """md の中のリンク。同梱する仕様は HTML へ向け、外部 URL はそのまま、
        同梱しないもの（TMF の PDF・Box・S3 のファイル）はリンクを外して文字だけ残す"""
        def f(text, url):
            u = url.strip()
            base = u.split('#')[0].rsplit('/', 1)[-1]
            if base in names:
                return '<a href="%s%s">%s</a>' % (names[base], u[len(u.split('#')[0]):], text)
            if u.startswith('#') or re.match(r'^https?://', u):
                return '<a href="%s"%s>%s</a>' % (html.escape(u),
                                                  '' if u.startswith('#') else
                                                  ' target="_blank"', text)
            return text
        return f

    total_ids = 0
    for f in have:
        src = os.path.join(REPO, 'docs', f)
        with open(src, encoding='utf-8') as fh:
            md = fh.read()
        body, toc = convert(md, links_for(f))
        m = re.search(r'^#\s+(.*)$', md, re.M)
        title = m.group(1).strip() if m else os.path.splitext(f)[0]
        # 戻り道。索引は1つ上のフォルダにある置き方（パッケージの 16_1_9_methods・作業用の
        # output/spec）を前提にする。生成の順で索引がまだ無いこともあるため実在は見ない
        back = ('<a class="back" href="%s">追跡索引へ戻る</a>' % args.back
                if args.back else '')
        tochtml = ''
        if len(toc) > 3:
            items, cur = [], 2
            for lv, key, txt in toc:
                if lv > cur:
                    items.append('<ul>')
                elif lv < cur:
                    items.append('</ul>')
                cur = lv
                items.append('<li><a href="#%s">%s</a></li>' % (key, html.escape(txt)))
            items.append('</ul>' * (cur - 1))
            tochtml = ('<nav class="toc"><div class="t">目次</div><ul>' +
                       ''.join(items) + '</nav>')
        page = ('<!DOCTYPE html>\n<html lang="ja">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
                '<title>' + html.escape(title) + '</title>\n<style>' + CSS +
                '</style>\n</head>\n<body>\n<header><div class="in">'
                '<span class="doc">' + html.escape(title) + '</span>' + back +
                '</div></header>\n<main>\n' + tochtml + body +
                '\n</main>\n<footer>正本は <code>docs/' + f + '</code>。'
                'この HTML は <code>scripts/build-spec-html.py</code> が作った派生物。'
                '</footer>\n</body>\n</html>\n')
        dst = os.path.join(outdir, names[f])
        open(dst, 'w', encoding='utf-8', newline='\n').write(page)
        n = len(re.findall(r'id="s-', page))
        total_ids += n
        if not args.quiet:
            print(f'  {names[f]}　節 {n}　{os.path.getsize(dst):,} バイト')
    print(f'仕様書 HTML {len(have)} 本（節の id {total_ids}）を {outdir} に書いた')
    miss = [f for f in FILES if f not in have]
    if miss:
        print('  docs に無いため作らなかったもの: ' + '、'.join(miss))


if __name__ == '__main__':
    main()
