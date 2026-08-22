# check-pi-package.py
#
# PI へ渡すパッケージが「フォルダごとどこへ置いても動く」ことを機械で確かめる。
# 手で開いて確かめると見落とすため、リンクの張り方を生成物の側で保証する。
#
#   - 外へ出るリンク（href・src・CSS の url()）に絶対 URL・絶対パスが無いか
#   - 相対リンクの先がパッケージの中に実在するか
#   - リンクがパッケージの外へ出ていないか（`../` で上へ抜けていないか）
#   - 錨（#fieldNN 等）がリンク先の HTML に実在するか
#
# 上へ抜けるリンクは、置いた場所にたまたま同名のファイルがあると手元では開けてしまい、
# 配った先で切れる。パッケージの外は見に行かず、抜けた時点で誤りとして扱う。
#
# 使い方
#   python scripts/check-pi-package.py            ... Box の最新のパッケージを見る
#   python scripts/check-pi-package.py <dir>      ... 置き場所を指定
import sys, os, re, glob, argparse, urllib.parse, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

# HTML は属性（href・src）と `<style>` の中の url()、CSS は url() だけを見る。CSS の中の
# `src="..."` は IE 用の AlphaImageLoader フィルタの書き方で、今のブラウザは取りに行かない。
# HTML 本文の url() を拾わないのは、仕様書を同梱するようになったため（`url(...)` の参照先を
# assets へ落とす、という文章そのものが本文に出てきてリンク切れと誤判定された）。
REF_ATTR = re.compile(r'(?:href|src)\s*=\s*"([^"]+)"')
REF_CSS = re.compile(r'url\(\s*[\'"]?([^\'")]+)[\'"]?\s*\)')
STYLE = re.compile(r'<style[^>]*>(.*?)</style>', re.S | re.I)
ANCHOR = re.compile(r'(?:id|name)\s*=\s*"([^"]+)"')


def latest_pkg():
    box = boxpath.trial_dir(required=False)
    if not box:
        return None
    c = sorted(glob.glob(os.path.join(box, 'output', boxpath.trial_id() + '_PI_*')))
    return c[-1] if c else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pkg', nargs='?', help='パッケージのフォルダ')
    a = ap.parse_args()
    pkg = a.pkg or latest_pkg()
    if not pkg or not os.path.isdir(pkg):
        sys.exit('パッケージが見つからない。フォルダを引数で渡す。')
    root = os.path.abspath(pkg)
    print(f'{root} を見る')

    files = [p for p in glob.glob(os.path.join(root, '**', '*'), recursive=True)
             if os.path.isfile(p) and p.rsplit('.', 1)[-1].lower() in ('html', 'htm', 'css')]
    err, warn = [], []
    anchors = {}          # ファイル → 錨の集合（開いた分だけ覚える）
    n_ref = 0

    def anchors_of(path):
        if path not in anchors:
            try:
                t = open(path, encoding='utf-8', errors='replace').read()
            except OSError:
                t = ''
            anchors[path] = set(ANCHOR.findall(t))
        return anchors[path]

    def check(rel, base, h, kind='リンク'):
        """1つの参照を見る。base はその参照が書かれていたファイルの場所"""
        if re.match(r'^[a-z][a-z0-9+.-]*:', h, re.I) or h.startswith('//'):
            err.append(f'{rel}: 絶対 URL「{h}」')
            return
        if h.startswith('/'):
            err.append(f'{rel}: 絶対パス「{h}」')
            return
        u = urllib.parse.urlparse(h)
        tgt = urllib.parse.unquote(u.path)
        frag = urllib.parse.unquote(u.fragment)
        if not tgt:
            return
        f = os.path.normpath(os.path.join(os.path.dirname(base), tgt))
        if os.path.commonpath([os.path.abspath(f), root]) != root:
            err.append(f'{rel}: パッケージの外を指す「{h}」')
            return
        if not os.path.exists(f):
            err.append(f'{rel}: {kind}先が無い「{h}」')
            return
        # 錨のうち `#n=out:...` の形はトレーサビリティ索引の画面遷移で、HTML の錨ではないので見ない
        if (frag and '=' not in frag and f.lower().endswith(('.html', '.htm'))
                and frag not in anchors_of(f)):
            warn.append(f'{rel}: 錨が無い「{h}」')

    # gzip のまま保存された CSS・HTML。HTTP 越しならブラウザが展開するが、`file://` では
    # ヘッダが無いため展開されず、体裁が当たらないまま黙って表示される
    for p in files:
        with open(p, 'rb') as f:
            if f.read(2) == b'\x1f\x8b':
                err.append(f'{os.path.relpath(p, root)}: gzip のまま保存されている')

    for p in files:
        rel = os.path.relpath(p, root)
        t = open(p, encoding='utf-8', errors='replace').read()
        if p.lower().endswith('.css'):
            refs = [m.group(1) for m in REF_CSS.finditer(t)]
        else:
            refs = [m.group(1) for m in REF_ATTR.finditer(t)]
            for st in STYLE.finditer(t):
                refs += [m.group(1) for m in REF_CSS.finditer(st.group(1))]
        for h in refs:
            h = h.strip()
            if not h or h.startswith('#') or h.startswith('data:') or h.startswith('mailto:'):
                continue
            # 生成物の中の JS が組み立てるリンク（'" + esc(o.url) + "'）は静的には見えない。
            # 素の文字列だけをここで見て、JS が使うデータ側は下の "url" の検査で見る。
            if "'" in h or '+' in h and '"' in h:
                continue
            n_ref += 1
            check(rel, p, h)
        # JS が組み立てるリンクの元（埋め込みデータの "url"）。トレーサビリティ索引がここから
        # aCRF と図表へのリンクを作るので、静的な href と同じ基準で見る。
        for h in set(re.findall(r'"url":"([^"]*)"', t)):
            if h:
                n_ref += 1
                check(rel, p, h, kind='データが指す')

        # 本文・データに混ざった外部 URL（リンクとして張られていないもの）。
        # w3.org は SVG・XLink の名前空間の宣言で、取りに行くものではないので除く。
        # CSS は取りに行くのが url() だけなので、註釈に書かれた出典の URL は見ない。
        if p.lower().endswith('.css'):
            continue
        for u in set(re.findall(r'https?://[^\s"\'<>]+', t)):
            if 'www.w3.org/' in u:
                continue
            warn.append(f'{rel}: 本文・データ中の外部 URL「{u[:80]}」')

    # R のコメントは仕様書を `docs/<名前>.md` の相対パスで指す。R を回す起点（reproduce/）から
    # 見て同じ位置に md が無いと、配った先で参照が辿れない。同梱は build-pi-package.py が行う。
    n_rmd = 0
    for p in sorted(glob.glob(os.path.join(root, 'reproduce', '*.R'))):
        rel = os.path.relpath(p, root)
        t = open(p, encoding='utf-8', errors='replace').read()
        for name in sorted(set(re.findall(r'docs/([\w.\-]+\.md)', t))):
            n_rmd += 1
            if not os.path.exists(os.path.join(root, 'reproduce', 'docs', name)):
                err.append(f'{rel}: コメントが指す docs/{name} が reproduce/docs に無い')

    print(f'ファイル {len(files)} / 見たリンク {n_ref} / R のコメントが指す仕様 {n_rmd}')
    for w in warn[:20]:
        print('WARN:', w)
    if len(warn) > 20:
        print(f'WARN: ほか {len(warn) - 20} 件')
    for e in err[:40]:
        print('ERROR:', e)
    if len(err) > 40:
        print(f'ERROR: ほか {len(err) - 40} 件')
    print(f'ERROR {len(err)} 件 / WARN {len(warn)} 件')
    sys.exit(1 if err else 0)


if __name__ == '__main__':
    main()
