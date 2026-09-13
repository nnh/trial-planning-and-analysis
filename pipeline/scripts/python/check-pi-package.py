# check-pi-package.py
#
# PI へ渡すパッケージが「フォルダごとどこへ置いても動く」ことを機械で確かめる。
# 手で開いて確かめると見落とすため、リンクの張り方を生成物の側で保証する。
#
#   - 外へ出るリンク（href・src・CSS の url()）に絶対 URL・絶対パスが無いか
#   - 相対リンクの先がパッケージの中に実在するか
#   - リンクがパッケージの外へ出ていないか（`../` で上へ抜けていないか）
#   - XML が指す外部ファイル（define.xml の表示用スタイルシート・補助資料）が同梱されているか
#   - 錨（#fieldNN 等）がリンク先の HTML に実在するか
#   - 同梱物の一覧（manifest.csv）が全ファイルを網羅し、SHA-256 が実物と一致するか
#   - 外へ出したくない文字列（端末のローカルパス・連絡先・外部サービスの識別子）が
#     本文に残っていないか。HTML だけでなく md・CSV・JSON・R・テキストも見る
#   - 同梱文書が案内するコマンドのオプションを、そのスクリプトが実際に受け付けるか
#   - Excel ブックが開ける形をしていて、チャートが系列・値・軸を持っているか
#   - 同梱した ADaM の define.xml が、いまの宣言と同梱のデータから作ったものと一致するか
#
# 検査の区分は3つで、それぞれ別の結果として出す。混ぜると「通った」の意味が曖昧になる。
#   可搬性     … リンクと錨。フォルダごとどこへ置いても開けるか
#   形式の健全性 … ファイルがその形式として読めるか（gzip のままでないか、zip が壊れていないか）
#   内容の健全性 … 中身が成果物として成立しているか（チャートの系列・軸、外へ出す文字列）
# 可搬性を通っただけでは中身は保証されない。2026-08-29 に Excel の生存曲線が系列を1本も
# 描かないまま全検査を通った（docs/validation/records/codex-review-2-ledger.md の C2-016・C2-022・C2-032）。
#
# 上へ抜けるリンクは、置いた場所にたまたま同名のファイルがあると手元では開けてしまい、
# 配った先で切れる。パッケージの外は見に行かず、抜けた時点で誤りとして扱う。
#
# 使い方
#   python scripts/check-pi-package.py            ... Box の最新のパッケージを見る
#   python scripts/check-pi-package.py <dir>      ... 置き場所を指定
#   python scripts/check-pi-package.py --allow-skip-define
#       ... スキル cdisc-define-xml が無い端末で、ADaM の define の再現の確認だけを飛ばす
import sys, os, re, csv, glob, hashlib, zipfile, argparse, subprocess, urllib.parse, collections

# 組み立ての途中で回すときに、この検査より後に作るファイルを未作成として許す集合。
# main が --pending から詰める（build-pi-package.py が検証の記録と同梱物の一覧を
# 検査の結果から作るため、1回目の検査ではまだ存在しない）
PENDING = set()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# HTML は属性（href・src）と `<style>` の中の url()、CSS は url() だけを見る。CSS の中の
# `src="..."` は IE 用の AlphaImageLoader フィルタの書き方で、今のブラウザは取りに行かない。
# HTML 本文の url() を拾わないのは、仕様書を同梱するようになったため（`url(...)` の参照先を
# assets へ落とす、という文章そのものが本文に出てきてリンク切れと誤判定された）。
REF_ATTR = re.compile(r'(?:href|src)\s*=\s*"([^"]+)"')
REF_CSS = re.compile(r'url\(\s*[\'"]?([^\'")]+)[\'"]?\s*\)')
STYLE = re.compile(r'<style[^>]*>(.*?)</style>', re.S | re.I)
ANCHOR = re.compile(r'(?:id|name)\s*=\s*"([^"]+)"')

# 外へ出したくない文字列。配る相手には開けないローカルパス、個人の連絡先、外部サービスの
# 識別子（そのまま外へ出すと、誰のどの置き場かが分かる）。この検査は組み立ての最後に
# 自動で回るので、組み立て側は同じ走査を持たない（規則を2か所に置くと食い違う）。
SECRET = [
    ('端末のローカルパス', re.compile(r'[A-Za-z]:\\Users\\[^\s"\'<>`|]+')),
    ('端末のローカルパス', re.compile(r'/(?:Users|home)/[A-Za-z0-9._-]+/[^\s"\'<>`|]+')),
    ('メールアドレス', re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')),
    ('Google ドキュメントの識別子', re.compile(r'docs\.google\.com/[^\s"\'<>`|]+')),
    ('Box の識別子', re.compile(r'\w*\.?box\.com/(?:file|folder|s)/[^\s"\'<>`|]+')),
]
# 本文を読む対象。被験者単位のデータ（Dataset-JSON と受領CSV）は値そのもので、大きいうえに
# 走査しても意味が無いので外す。仕様・宣言・コード・記録を見る
TEXT_EXT = ('md', 'csv', 'json', 'r', 'py', 'txt', 'xml', 'lock')
TEXT_SKIP = ('data/sdtm/', 'data/adam/', 'reproduce/input/rawdata/', 'reproduce/input/ext/')
MANIFEST = ('manifest.csv', 'manifest.html')

# 同梱文書が案内するコマンドのオプション。突き合わせる相手は文書側の宣言ではなく実装の
# 事実（スクリプトの argparse が受け付ける集合）なので、この検査は写しを増やさない。
# 2026-08-30 に廃止した `--with-subject-data` が、納品パッケージへ同梱される仕様書の
# コマンド例に残り、PI は「既定では入らない」と書いた文書と全部入っているパッケージを
# 同時に受け取っていた（2026-09-05。C3-323）。
#
# 見るのは、スクリプト名と同じ文の中に書かれたオプションだけにする。文書のどこかに出る
# `--…` を全部見ると、CSS のカスタムプロパティ（`--muted`）・R と renv の起動オプション・
# CDISC CORE の引数が混ざって使い物にならない（20260831 版の実測で、文単位なら該当2件・
# 誤検出0件、ファイル単位では71件）。同じ理由で、スクリプト名を伴わない散文の中の
# オプション（「`--with-subject-data` を明示したときだけ入れる」のような書き方）は
# 捕まらない。
CLI_FLAG = re.compile(r'--[a-z][a-z0-9-]{2,}')
CLI_SCRIPT = re.compile(r'[a-z0-9][a-z0-9_-]*\.py')
CLI_SPLIT = re.compile(r'<[^>]+>|[、。]')

# 配布形式の登録。どの形式をどの検査に掛けるかをここだけで決める。同梱する形式を増やしたら
# ここへ足す。登録の無い拡張子が混ざったときは、その形式にはどの検査も当たっていないので
# 指摘する。2026-08-29 に `.xlsx` が登録されないまま同梱され、Excel の生存曲線が系列を
# 1本も描かない状態で全検査を通った（C2-002・C2-022）。
LINK_EXT = ('html', 'htm', 'css')                    # 可搬性（リンク・錨）を見る
BOOK_EXT = ('xlsx',)                                 # 形式の健全性とチャートの構造を見る
ASSET_EXT = ('png', 'jpg', 'jpeg', 'gif', 'svg', 'pdf',
             'ttf', 'otf', 'eot', 'woff', 'woff2',
             'xsl')                                  # 参照先として実在だけを見る資産
KNOWN_EXT = LINK_EXT + BOOK_EXT + TEXT_EXT + ASSET_EXT + ('rprofile',)

# XML が指す外部ファイル。define.xml は表示用のスタイルシートを <?xml-stylesheet?> で、
# 補助資料を def:leaf の xlink:href で指す。リンクの検査が html・htm・css にしか掛かって
# いなかったため、define2-0-0.xsl が同梱されていないことに気づけず、PI が define.xml を
# 直接開くとスタイルの当たらない生の XML が出る状態が続いた（2026-09-05。段E）。
# スタイルシートは表示そのものが成り立たなくなるので誤り、それ以外の参照は同梱しないと
# 決めたもの（注釈付き CRF の PDF）があるので警告として出す。
XML_XSL = re.compile(r'<\?xml-stylesheet[^?>]*href="([^"]+)"')
XML_LEAF = re.compile(r'xlink:href="([^"]+)"')

# Excel のチャート（DrawingML）。ブックは zip で、xl/charts/chartN.xml が1図に対応する。
# 系列は c:ser、値は c:yVal（散布図）か c:val（折れ線・棒）、軸は c:valAx / c:catAx で
# 位置を c:axPos が持つ。参照先のセル範囲は c:f に「シート名!範囲」の形で入る。
CH_SHEET = re.compile(r'<sheet [^>]*name="([^"]+)"')
CH_SER = re.compile(r'<c:ser>.*?</c:ser>', re.S)
CH_TX = re.compile(r'<c:tx>.*?</c:tx>', re.S)
CH_F = re.compile(r'<c:f>([^<]*)</c:f>')
CH_V = re.compile(r'<c:v>([^<]*)</c:v>')
CH_Y = re.compile(r'<c:(yVal|val)>.*?</c:\1>', re.S)
CH_AX = re.compile(r'<c:(valAx|catAx|dateAx)>(.*?)</c:\1>', re.S)
CH_AXPOS = re.compile(r'<c:axPos val="([^"]+)"')
CH_SYMBOL = re.compile(r'<c:symbol val="([^"]+)"')
CH_MAX = re.compile(r'<c:max val="([^"]+)"')
CH_MIN = re.compile(r'<c:min val="([^"]+)"')


def all_files(root):
    """パッケージの中の全ファイル（root からの相対パス）。

    glob は既定で先頭が `.` のファイルを拾わないため、os.walk で数える
    （`reproduce/.Rprofile` を落とすと、同梱物の一覧との照合が食い違う）。
    """
    return sorted(os.path.relpath(os.path.join(r, f), root).replace(os.sep, '/')
                  for r, _, fs in os.walk(root) for f in fs)


def script_flags():
    """リポジトリの `scripts/*.py` が受け付ける長いオプション。argparse の呼び出しを読む。

    正本はスクリプトそのもので、受け付ける集合の写しをここに持たない。リポジトリの外で
    パッケージだけを見る端末では空を返し、この検査を飛ばす（declared_figures と同じ扱い）。
    """
    out = {}
    for p in sorted(glob.glob(os.path.join(REPO, 'scripts', '*.py'))):
        t = open(p, encoding='utf-8', errors='replace').read()
        out[os.path.basename(p)] = set(
            re.findall(r"add_argument\(\s*'(--[a-z0-9-]+)'", t))
    return out


def declared_figures():
    """図表宣言（docs/metadata/tlf-index.csv）から、図として宣言された `lblid` を採る。

    何件あるかはここでは持たず、宣言を数えて得る。宣言が正本で、この検査は写しを持たない。
    宣言が読めない端末（リポジトリの外でパッケージだけを見るとき）は None を返し、
    チャートの中身だけを見る。
    """
    p = os.path.join(REPO, 'docs', 'metadata', 'tlf-index.csv')
    if not os.path.isfile(p):
        return None, None
    with open(p, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    return ({r['lblid'] for r in rows if r['display'].startswith('fig_')},
            {r['lblid'] for r in rows})


def sheet_of(f):
    """チャートのセル参照（`F_5_4_1!$B$36:$B$36` や `'F 1'!$A$1`）からシート名を採る"""
    s = f.rsplit('!', 1)[0] if '!' in f else ''
    return s.strip("'")


def chart_facts(xml):
    """チャート1つ分の XML から、描画結果の成否が分かる事実だけを抜く。

    見るのは系列（名前・値・打切り印の有無）と軸（位置・目盛りの範囲）である。
    体裁（色・書体・凡例の位置）は成果物の正否に関わらないので読まない。
    """
    sers = []
    for s in CH_SER.findall(xml):
        tx = CH_TX.search(s)
        name = (CH_V.search(tx.group(0)).group(1) if tx and CH_V.search(tx.group(0)) else '')
        y = CH_Y.search(s)
        vals = []
        if y:
            for v in CH_V.findall(y.group(0)):
                try:
                    vals.append(float(v))
                except ValueError:
                    pass
        sym = CH_SYMBOL.search(s)
        sers.append({'name': name, 'vals': vals,
                     'marker': bool(sym) and sym.group(1) != 'none'})
    axes = []
    for kind, body in CH_AX.findall(xml):
        pos = CH_AXPOS.search(body)
        mx, mn = CH_MAX.search(body), CH_MIN.search(body)
        axes.append({'kind': kind, 'pos': pos.group(1) if pos else '',
                     'max': float(mx.group(1)) if mx else None,
                     'min': float(mn.group(1)) if mn else None})
    f = CH_F.search(xml)
    return {'sheet': sheet_of(f.group(1)) if f else '', 'ser': sers, 'ax': axes}


def check_book(rel, path, figs, lbls, err, warn):
    """Excel ブック1冊を見る。形式として読めるか、チャートが図として成立しているか。

    リンク検査は「ブックが同梱されていて開ける」までしか見ない。2026-08-29 に生存曲線が
    系列を1本も持たない Excel が全検査を通ったので、チャートの構造まで踏み込む
    （docs/validation/records/codex-review-2-ledger.md の C2-016・C2-032）。
    """
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        err.append(f'{rel}: Excel ブックとして開けない')
        return 0
    with z:
        if '[Content_Types].xml' not in z.namelist():
            err.append(f'{rel}: Excel ブックの体を成していない')
            return 0
        try:
            book = z.read('xl/workbook.xml').decode('utf-8', 'replace')
        except KeyError:
            err.append(f'{rel}: xl/workbook.xml が無い')
            return 0
        sheets = set(CH_SHEET.findall(book))
        charts = sorted(n for n in z.namelist()
                        if re.fullmatch(r'xl/charts/chart\d+\.xml', n))
        seen = set()
        for n in charts:
            c = chart_facts(z.read(n).decode('utf-8', 'replace'))
            who = f'{rel}:{c["sheet"] or n}'
            seen.add(c['sheet'])
            if not c['ser']:
                err.append(f'{who}: 系列が1本も無い')
                continue
            for s in c['ser']:
                nm = s['name'] or '（名前なし）'
                if not s['vals']:
                    err.append(f'{who}: 系列「{nm}」に値が無い')
                elif len(set(s['vals'])) == 1 and s['vals'][0] == 0:
                    err.append(f'{who}: 系列「{nm}」の値がすべて0')
            # 軸は横1つ・縦1つ。二重に置くと目盛りとラベルが重なって出る
            h = [a for a in c['ax'] if a['pos'] in ('b', 't')]
            v = [a for a in c['ax'] if a['pos'] in ('l', 'r')]
            if len(h) != 1 or len(v) != 1:
                err.append(f'{who}: 軸が横{len(h)}・縦{len(v)}（横1・縦1であること）')
            # 縦軸は割合か百分率。KM 曲線は 0 から 1（または 0 から 100）に収まる
            for a in v:
                if a['min'] is not None and a['min'] != 0:
                    warn.append(f'{who}: 縦軸の下端が {a["min"]}（0 であること）')
                if a['max'] is not None and a['max'] not in (1, 100):
                    warn.append(f'{who}: 縦軸の上端が {a["max"]}（1 か 100 であること）')
            # 図として宣言されたものは打切り印を持つ。印の系列が消えると曲線だけが残り、
            # 見た目は成立しているのに情報が落ちる
            if figs and c['sheet'] in figs and not any(s['marker'] for s in c['ser']):
                err.append(f'{who}: 打切り印の系列が無い')
        # 宣言された図がブックに1つも無い、という取りこぼしを見る。図表のブック
        # （宣言された `lblid` のシートを持つもの）だけが対象で、他のブックは見ない
        if figs and lbls and (sheets & lbls):
            for k in sorted(figs - seen):
                err.append(f'{rel}: 宣言された図 {k} のチャートが無い')
        return len(charts)


def latest_pkg():
    box = boxpath.trial_dir(required=False)
    if not box:
        return None
    # 納品パッケージの置き場は output/deliver/r/。旧構成（output/ 直下）にも残っている
    # 場合があるので両方見て、名前の並びで最後（日付が新しいもの）を採る
    c = sorted(glob.glob(os.path.join(box, 'output', 'deliver', 'r',
                                      boxpath.trial_id() + '_PI_*'))
               + glob.glob(os.path.join(box, 'output', boxpath.trial_id() + '_PI_*')),
               key=lambda p: os.path.basename(p))
    return c[-1] if c else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pkg', nargs='?', help='パッケージのフォルダ')
    ap.add_argument('--pending', default='',
                    help='まだ作っていないファイル（コンマ区切り）。組み立ての途中で回すとき、'
                         '検査の結果を載せる記録や同梱物の一覧のように、この検査より後に作る'
                         'ものを指すリンクを未作成として許す')
    ap.add_argument('--allow-skip-define', action='store_true',
                    help='ADaM の define.xml を作り直して突き合わせる検査を飛ばす。'
                         '生成の本体はスキル cdisc-define-xml にあるので、それが無い端末で使う')
    a = ap.parse_args()
    PENDING.update(x.strip().replace('\\', '/') for x in a.pending.split(',') if x.strip())
    pkg = a.pkg or latest_pkg()
    if not pkg or not os.path.isdir(pkg):
        sys.exit('パッケージが見つからない。フォルダを引数で渡す。')
    root = os.path.abspath(pkg)
    # フォルダ名だけを出す。この標準出力は検証の記録として納品物へ載るので、
    # 絶対パスを出すと組み立てた端末の Box の位置が残る（2026-08-31。C2-219）
    print(f'{os.path.basename(root)} を見る')

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

    def secrets(rel, t):
        """外へ出したくない文字列を1ファイル分見る。

        同じ文書に同種のものが何度も出るので、ファイルと種類ごとに件数と1例へまとめる。
        1件ずつ並べると数百行になり、リンクの誤りが埋もれる。
        """
        for kind, pat in SECRET:
            m = sorted(set(pat.findall(t)))
            if m:
                warn.append(f'{rel}: {kind} {len(m)} 件（例 {m[0][:60]}）')

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
            # この検査より後に作るファイル（検証の記録・同梱物の一覧）は未作成を許す
            if os.path.relpath(f, root).replace(os.sep, '/') in PENDING:
                return
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

        # 端末のローカルパス・連絡先・外部サービスの識別子。配る相手には開けず、
        # ユーザー名や職員番号をそのまま外へ出すことになる。2026-08-29 に納品物の3ファイルで
        # 見つかった（固定前の作業記録に書かれた Plan mode の作業ファイル・参考実装・端末の識別）。
        secrets(rel, t)

    # XML が指す外部ファイル。被験者単位データの置き場（data/sdtm・data/adam）にある
    # define.xml が対象なので、本文の走査で外している TEXT_SKIP はここでは掛けない
    n_xml = 0
    for rel in all_files(root):
        if rel.rsplit('.', 1)[-1].lower() != 'xml':
            continue
        p = os.path.join(root, rel)
        t = open(p, encoding='utf-8', errors='replace').read()
        for h in sorted(set(XML_XSL.findall(t))):
            n_xml += 1
            check(rel, p, h, kind='スタイルシートの')
        for h in sorted(set(XML_LEAF.findall(t))):
            if h.startswith('#') or h.startswith('data:'):
                continue
            n_xml += 1
            f = os.path.normpath(os.path.join(os.path.dirname(p), urllib.parse.unquote(h)))
            if not os.path.exists(f):
                warn.append(f'{rel}: XML が指す「{h}」を同梱していない')

    # R のコメントは仕様書を `docs/<名前>.md` の相対パスで指す。R を回す起点（reproduce/）から
    # 見て同じ位置に md が無いと、配った先で参照が辿れない。同梱は build-pi-package.py が行う。
    n_rmd = 0
    for p in sorted(glob.glob(os.path.join(root, 'reproduce', 'program', 'r', '*.R'))):
        rel = os.path.relpath(p, root)
        t = open(p, encoding='utf-8', errors='replace').read()
        for name in sorted(set(re.findall(r'docs/([\w.\-]+\.md)', t))):
            n_rmd += 1
            if not os.path.exists(os.path.join(root, 'reproduce', 'docs', name)):
                err.append(f'{rel}: コメントが指す docs/{name} が reproduce/docs に無い')

    # HTML 以外の同梱物（仕様の md・宣言の CSV・R・実行環境の記録）も本文を見る。
    # リンクの検査と違い、こちらは中身がそのまま外へ出ることを見ている
    n_txt = 0
    for rel in all_files(root):
        p = os.path.join(root, rel)
        # `.Rprofile` のように先頭が `.` のファイルも見る（glob は既定で拾わない）
        if (rel.rsplit('.', 1)[-1].lower() not in TEXT_EXT or rel.startswith(TEXT_SKIP)):
            continue
        n_txt += 1
        secrets(rel, open(p, encoding='utf-8', errors='replace').read())

    # 同梱文書が案内するコマンドのオプションを、そのスクリプトの argparse と突き合わせる。
    # 廃止したオプションが仕様書のコマンド例に残ると、受け取った側は動かない手順を渡される
    known = script_flags()
    n_cli = 0
    for rel in all_files(root):
        if (rel.rsplit('.', 1)[-1].lower() not in TEXT_EXT + LINK_EXT
                or rel.startswith(TEXT_SKIP)):
            continue
        for line in open(os.path.join(root, rel), encoding='utf-8', errors='replace'):
            for seg in CLI_SPLIT.split(line):
                names = sorted(n for n in set(CLI_SCRIPT.findall(seg)) if n in known)
                if not names:
                    continue
                ok = set().union(*(known[n] for n in names))
                for fl in CLI_FLAG.findall(seg):
                    n_cli += 1
                    if fl not in ok:
                        err.append(f'{rel}: {"・".join(names)} が受け付けない'
                                   f'オプション「{fl}」を案内している')

    # Excel ブック。開ける形をしているか（形式の健全性）と、チャートが図として成立して
    # いるか（内容の健全性）を見る。リンク検査は同梱と参照までしか見ない
    figs, lbls = declared_figures()
    n_book = n_chart = 0
    for rel in all_files(root):
        if rel.rsplit('.', 1)[-1].lower() not in BOOK_EXT:
            continue
        n_book += 1
        n_chart += check_book(rel, os.path.join(root, rel), figs, lbls, err, warn)

    # 登録の無い形式。どの検査にも掛かっていないものが黙って同梱される状態を避ける
    for e, n in sorted(collections.Counter(
            rel.rsplit('.', 1)[-1].lower() for rel in all_files(root)
            if '.' in os.path.basename(rel)).items()):
        if e not in KNOWN_EXT:
            warn.append(f'配布形式の登録が無い拡張子「.{e}」が {n} 件（KNOWN_EXT へ足す）')

    # 同梱物の一覧。受け取った側が欠けと取り違えを自分で確かめられる形になっているか、
    # 一覧の値が実物と合っているかを見る（組み立ての途中では一覧がまだ無い）
    man = os.path.join(root, 'manifest.csv')
    n_man = 0
    if not os.path.exists(man):
        warn.append('manifest.csv が無い（同梱物の一覧を作る前の状態）')
    else:
        listed = {}
        with open(man, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                listed[row['path']] = (int(row['bytes']), row['sha256'])
        have = set(all_files(root)) - set(MANIFEST)
        for rel in sorted(have - set(listed)):
            err.append(f'manifest.csv: {rel} が一覧に無い')
        for rel in sorted(set(listed) - have):
            err.append(f'manifest.csv: 一覧にある {rel} が同梱されていない')
        for rel in sorted(have & set(listed)):
            n_man += 1
            p = os.path.join(root, rel)
            h = hashlib.sha256()
            with open(p, 'rb') as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b''):
                    h.update(chunk)
            if (os.path.getsize(p), h.hexdigest()) != listed[rel]:
                err.append(f'manifest.csv: {rel} の大きさか SHA-256 が実物と違う')

    # 同梱した ADaM の define.xml が、いまの宣言（docs/metadata/variable-map.csv・
    # adam-codelist.csv）と同梱のデータ（data/adam/*.json）から作ったものと一致するか。
    #
    # 2026-09-05 に、ADSL の ABLMUTFL の predecessor を ADSL.ABLMUT から
    # FA.FATESTCD/FA.FASTAT へ直したのに define.xml の def:Origin が古いままのものが、
    # 納品パッケージへ入りかけた。当時 ADaM の define.xml は通し実行の外にあり、作り直して
    # いないものが同梱されても誰も気づけなかった。通し実行には段階を足したが
    # （scripts/run-adam-validation.py）、
    # 組み立てはそれとは別のコマンドなので、入る直前にもう一度ここで見る。
    #
    # 材料はパッケージの中で閉じる（同梱の Dataset-JSON を読む）ので Box は要らない。
    # 生成の本体はスキル cdisc-define-xml にあるため、それが無い端末では作り直せない。
    # そのときは黙って通さず、何を確かめていないかを述べて誤りとして挙げる（C3-124）。
    n_def = 0
    adam_xml = os.path.join(root, 'data', 'adam', 'define.xml')
    if not os.path.exists(adam_xml):
        err.append('data/adam/define.xml が同梱されていない')
    elif a.allow_skip_define:
        warn.append('--allow-skip-define のため ADaM の define.xml の再現を確かめていない')
    else:
        p = subprocess.run(
            [sys.executable, os.path.join(REPO, 'scripts', 'build-adam-define.py'),
             '--json-dir', os.path.dirname(adam_xml), '--compare', adam_xml],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace')
        if p.returncode == 0:
            n_def = 1
        else:
            last = [x for x in (p.stdout or '').splitlines() if x.strip()]
            err.append('data/adam/define.xml がいまの宣言と同梱のデータから作ったものと'
                       '一致しない、または作り直せない: '
                       + (last[-1][:200] if last else '出力なし'))

    # 配る経路で落ちやすい名前を見る。先頭がドットのファイルは Box Drive の同期で
    # 消えることがあり、reproduce/.Rprofile が実際に落ちていた（2026-09-06 の独立レビュー
    # の所見1）。落ちると renv が活性化されず lock と違う版で走る。ドットに依らない入口
    # （reproduce/run.R）があることを確かめ、無ければ落とす。ドット始まりの同梱物そのものは
    # 残してよいので、在ることは警告に留める
    dotted = [p for p in all_files(root)
              if os.path.basename(p).startswith('.')]
    n_dot = len(dotted)
    run_r = os.path.join(root, 'reproduce', 'run.R')
    if not os.path.exists(run_r):
        err.append('reproduce/run.R が無い。先頭がドットのファイルに依らない入口が'
                   '要る（配る経路で .Rprofile が落ちると renv が活性化されない）')
    for d in dotted:
        warn.append(f'配る経路で落ちやすい名前（先頭がドット）: {d}。'
                    f'入口は reproduce/run.R が受ける')
    print(f'可搬性 : ファイル {len(files)} / 見たリンク {n_ref} / '
          f'XML が指す外部ファイル {n_xml} / R のコメントが指す仕様 {n_rmd} / '
          f'先頭がドットの同梱物 {n_dot}')
    print(f'形式・内容 : Excel ブック {n_book} / チャート {n_chart} / '
          f'本文を見た同梱物 {n_txt} / 案内するオプション {n_cli} / 一覧と照合 {n_man} / '
          f'ADaM の define の再現 {n_def}')
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
