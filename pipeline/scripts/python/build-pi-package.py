# build-pi-package.py
#
# PI へ渡す一式を1つのフォルダへ組み立てる。手で集めると版が混ざるため必ずこれを通す。
#
# 階層は ICH E3（総括報告書の構成）の番号を骨格にする。14章が本文から参照する図表、
# 16.1.2 が CRF の見本、16.1.9 が統計手法の記録、16.2 が被験者データ一覧。重篤な有害事象の
# 経過（narratives）は E3 が 14.3.3 に置くものなので 14_3_3_narratives へ入れる。トレーサビリティ索引は
# E3 の構成要素ではないのでルート直下に置き、相対パスで 14章と 16.1.2 を参照する。
# 設計の正本は docs/spec/label-and-traceability-design.md の「PI 向けパッケージ」。
#
#   <試験ID>_PI_YYYYMMDD/
#     README.html                    入口
#     traceability.html              トレーサビリティ索引（14_tlf と 16_1_2_acrf を相対で参照）
#     14_tlf/ja/<表番号>.html         図表ごと（日本語。索引が既定で指す）
#     14_tlf/en/<表番号>.html         図表ごと（英語）
#     14_tlf/*.html                  通し読み用
#     14_tlf/*.xlsx                  言語ごとに1ブック（1図表=1シート。KM はネイティブなチャート）
#     14_3_3_narratives/             重篤な有害事象の経過（PI 向けの読み物。外部提供の対象外）
#     16_1_2_acrf/<帳票>.html         注釈付き CRF 62帳票（#fieldNN の錨つき）
#     16_1_9_methods/                define.html（SDTM・ADaM）と仕様の HTML（節に錨つき）
#     data/ard/                      ARD（集計値。被験者単位ではない）
#     reproduce/                     R 一式と仕様ファイル（input/spec）
#     16_2_listings/ ・ data/sdtm ・ data/adam ・ reproduce/input   ... --with-subject-data のときだけ
#
# 被験者単位のデータは既定で入れない。配布先ごとに判断するため、明示の指定を要る形にする。
#
# 使い方
#   python scripts/build-pi-package.py                      ... Box の output/ へ作る
#   python scripts/build-pi-package.py --out <dir>          ... 置き場所を指定
#   python scripts/build-pi-package.py --with-subject-data  ... 被験者単位データも入れる
#   python scripts/build-pi-package.py --acrf-dir <dir>     ... aCRF を取得済みのフォルダから写す
import sys, os, re, csv, glob, gzip, json, shutil, argparse, datetime, subprocess
import urllib.request, urllib.parse, concurrent.futures, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, 'scripts')
LOCK = threading.Lock()          # 62帳票が共有する CSS の取得を1回に絞る


def sh(*args):
    print('  $ ' + ' '.join(str(a) for a in args))
    # encoding を明示する。Windows の既定は cp932 で、子プロセスが出す
    # UTF-8 の日本語を読めずに落ちる
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    if r.returncode:
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        sys.exit(f'失敗: {" ".join(str(a) for a in args)}')
    return r.stdout


def copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


# 図表 HTML に埋まっている相対リンクは作業用の並び（output/tlf/r-<言語>/ から
# output/deliver/r/traceability.html を見る形）で書かれている。パッケージでは索引が直下、
# 図表が 14_tlf/<言語>/ なので、写すときに書き換える。図表を2度描かずに済ませるため、
# 書き換えはここ1箇所に閉じる（作業用の並びは TLF.R の IX と言語間リンクが正本）。
TLF_LINK_FIX = [('../../deliver/r/traceability.html', '../../traceability.html'),
                ('../r-ja/', '../ja/'),
                ('../r-en/', '../en/')]


def copy_tlf(src, dst, pat='*'):
    """図表 HTML を写し、パッケージ内の並びに合わせてリンクを書き換える"""
    n = 0
    for p in sorted(glob.glob(os.path.join(src, pat))):
        if not os.path.isfile(p):
            continue
        b = os.path.basename(p)
        if re.search(r' \([^()]*@[^()]*\)', b):
            print(f'  同期の競合の写しを外した: {b}')
            continue
        t = open(p, encoding='utf-8').read()
        for a, c in TLF_LINK_FIX:
            t = t.replace(a, c)
        os.makedirs(dst, exist_ok=True)
        open(os.path.join(dst, b), 'w', encoding='utf-8', newline='\n').write(t)
        n += 1
    return n


# --- 納品してよい文書の境界 ---------------------------------------------------------
#
# R のコメントが指す md を集め、その md が指す md も辿るので、境界を置かないと
# 芋づる式に内部文書まで入る。2026-08-29 の版には、データセンターへの照会メール案、
# 独立レビューの実施記録、SAP 本体への修正指示書、日次の作業ログが入っていた。
#
# 許可はディレクトリで決める。同梱してよいのは、実装が従う仕様（spec）と規制文書（tmf）の
# 全部と、records のうちここに名前を挙げたものだけである。records を名前で挙げるのは、
# 新しい記録を足したときに黙って納品物へ入らないようにするため。既定は「入れない」にする。
#
# 挙げてよいのは、結果の値がなぜそうなるかを説明する記録に限る。内部の品質管理・環境の
# 検証・作業中の指示は、PI が読む前提で書かれていないので入れない。
DOC_DIRS = ('spec/', 'tmf/')
DOC_RECORDS = {
    'records/cmr-derivation-findings-20260819.md',      # CMR 判定の導出
    'records/sdtm-conformance-findings-20260815.md',    # 適合性検証の結果と仕分け
    'records/rawdata-value-scan-20260809.md',           # 受領データの実値の走査
    'records/ecrf-reference-field-issue-20260809.md',   # eCRF の不具合（データの制約）
    'records/dscat-disposition-event-note.md',          # 観察終了の扱い
}


def doc_allowed(name):
    """docs からの相対パスが納品してよいものか"""
    n = name.replace(os.sep, '/').lstrip('./')
    return n.startswith(DOC_DIRS) or n in DOC_RECORDS


def drop_links(text, here):
    """同梱しない md へのリンクを、素の文字列と断り書きへ落とす。

    リンクのまま残すとパッケージの中で参照先が無くなり、check-pi-package.py が落ちる。
    参照していた事実は本文に残したいので、消さずに文字列にする。
    """
    def repl(m):
        label, target = m.group(1), m.group(2)
        rel = os.path.normpath(os.path.join(here, target)).replace(os.sep, '/')
        if doc_allowed(rel):
            return m.group(0)
        return f'{label}（内部の記録のため同梱していない）'
    return re.sub(r'\[([^\]]*)\]\(([\w.\-/]+\.md)\)', repl, text)


def copy_tree(src, dst, pat='*'):
    n = 0
    for p in sorted(glob.glob(os.path.join(src, pat))):
        if not os.path.isfile(p):
            continue
        # Box Drive が同期の競合で作る写し（`T_4_5_2 (311-system+box.team-k@…).html`）は
        # PI へ渡す形に入れない。消さずに Box へ残しておき、別の端末の変更を取り込んでから
        # 図表を作り直して片付ける（どちらが新しいかを人が判断する必要があるため）
        b = os.path.basename(p)
        if re.search(r' \([^()]*@[^()]*\)', b):
            print(f'  同期の競合の写しを外した: {b}')
            continue
        copy(p, os.path.join(dst, b))
        n += 1
    return n


def localize_css(path, src_url, assets, prefix, get):
    """CSS の中の `url(...)` を手元のファイルへ向ける。

    Ptosh の共通 CSS は背景画像とアイコン用の書体を別ホスト（ptosh-assets）から読む。
    そのままでは網が無いと当たらないため、参照先を assets/ へ落として相対パスへ差し替える。
    取れなかった参照は `none` にして外へ出るリンクを残さない。背景画像とアイコン用の書体
    なので、無くても帳票は読める。
    """
    t = open(path, encoding='utf-8', errors='replace').read()
    lost = []

    def repl(m):
        raw = m.group(1).strip().strip('\'"')
        if not raw or raw.startswith('data:'):
            return m.group(0)
        body, sep, frag = raw.partition('#')
        body = body.split('?')[0]
        full = urllib.parse.urljoin(src_url, 'https:' + body if body.startswith('//') else body)
        fn = os.path.basename(urllib.parse.urlparse(full).path)
        if not fn:
            return m.group(0)
        dst = os.path.join(assets, fn)
        if not os.path.exists(dst):
            b = get(full)
            if b is None:
                lost.append(raw)
                return 'none'
            open(dst, 'wb').write(b)
        return 'url(' + prefix + fn + (sep + frag if sep else '') + ')'

    t2 = re.sub(r'url\(\s*([^)]+?)\s*\)', repl, t)
    if t2 != t:
        open(path, 'w', encoding='utf-8', newline='\n').write(t2)
    if lost:
        ex = f'（{lost[0]} ほか {len(lost) - 1}）' if len(lost) > 1 else f'（{lost[0]}）'
        print(f'  aCRF: {os.path.basename(path)} の参照 {len(lost)} 件が取れず外した' + ex)


# --- aCRF（S3 の HTML）を持ってきて、外部の CSS もローカルへ寄せる -----------------------
def fetch_acrf(dest):
    """aCRF を dest へ置く。参照している CSS も落として相対パスへ書き換える。

    aCRF は Ptosh が生成した HTML で、共通の CSS（別ホスト）と帳票ごとの CSS
    （`./<スラッグ>/style.css`）を読む。そのままでは手元で開いたときに崩れるため、
    assets/ へ集めてリンクを差し替える。項目単位の錨（#fieldNN）は HTML のままなので、
    PDF ではなく HTML を同梱する（索引から項目へ飛ぶのに要る）。
    """
    rows = []
    for p in sorted(glob.glob(os.path.join(REPO, 'docs', 'tmf', 'aCRF', '*-acrf.csv'))):
        with open(p, encoding='utf-8-sig', newline='') as f:
            for row in csv.reader(f):
                if len(row) > 1 and row[1].strip():
                    rows.append((row[0].strip(), row[1].strip()))
    os.makedirs(dest, exist_ok=True)
    assets = os.path.join(dest, 'assets')
    os.makedirs(assets, exist_ok=True)

    def get(url, timeout=30):
        """取得して、gzip で置かれているものは展開する。

        S3 の CSS は gzip 圧縮した実体に `Content-Encoding: gzip` を付けて置かれている。
        HTTP 越しならブラウザが展開するが、そのまま保存して `file://` から読むと
        ヘッダが無いため展開されず、体裁が当たらない（2026-08-20 に実際に崩れた）。
        """
        req = urllib.request.Request(url, headers={'Accept-Encoding': 'identity'})
        for _ in range(3):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as f:
                    b, enc = f.read(), (f.headers.get('Content-Encoding') or '').lower()
                if 'gzip' in enc or b[:2] == b'\x1f\x8b':
                    b = gzip.decompress(b)
                return b
            except Exception:
                pass
        return None

    def one(item):
        name, url = item
        slug = url.rsplit('/', 1)[-1].replace('.html', '')
        base = url.rsplit('/', 1)[0]
        b = get(url)
        html = b.decode('utf-8', 'replace') if b else None
        if html is None:
            return (slug, 'ERR')
        # 帳票ごとの CSS
        for css in re.findall(r'href="\./' + re.escape(slug) + r'/([^"]+)"', html):
            u = base + '/' + slug + '/' + css
            b = get(u)
            if b:
                d = os.path.join(dest, slug)
                os.makedirs(d, exist_ok=True)
                p = os.path.join(d, css)
                open(p, 'wb').write(b)
                localize_css(p, u, assets, '../assets/', get)
        # 別ホストの共通 CSS を assets へ寄せてリンクを差し替える。62帳票が同じ CSS を
        # 指すので、書き込みは1回だけにする（並行して取ると書きかけを読む）
        for m in re.finditer(r'href="(//[^"]+\.css)"', html):
            u = 'https:' + m.group(1)
            fn = u.rsplit('/', 1)[-1]
            with LOCK:
                if not os.path.exists(os.path.join(assets, fn)):
                    b = get(u)
                    if b:
                        open(os.path.join(assets, fn), 'wb').write(b)
                        localize_css(os.path.join(assets, fn), u, assets, '', get)
            if os.path.exists(os.path.join(assets, fn)):
                html = html.replace(m.group(1), 'assets/' + fn)
        # 外部の JavaScript と favicon は落とす。aCRF は静的な帳票の見本で、
        # Ptosh の JS は入力画面の動きのためのもの。手元で開くと取得できず待たされるだけ。
        html = re.sub(r'<script[^>]*>.*?</script>\s*', '', html, flags=re.S)
        html = re.sub(r'<link[^>]*rel="shortcut icon"[^>]*>\s*', '', html)
        open(os.path.join(dest, slug + '.html'), 'w', encoding='utf-8',
             newline='\n').write(html)
        return (slug, 'OK')

    with concurrent.futures.ThreadPoolExecutor(6) as ex:
        res = list(ex.map(one, rows))
    ng = [s for s, st in res if st != 'OK']
    return len(res) - len(ng), ng


def write_acrf_index(dest):
    """aCRF の目次。CSR の 16.1.2 は blankcrf.pdf 1本を置く体裁だが、ここは帳票ごとの
    HTML（項目単位の錨つき）なので、帳票の並び順を保った目次を1枚置いて入口にする。
    define.html が blankcrf.pdf を指す先もここへ差し替える。
    """
    rows = []
    for p in sorted(glob.glob(os.path.join(REPO, 'docs', 'tmf', 'aCRF', '*-acrf.csv'))):
        with open(p, encoding='utf-8-sig', newline='') as f:
            for row in csv.reader(f):
                if len(row) > 1 and row[1].strip():
                    slug = row[1].strip().rsplit('/', 1)[-1].replace('.html', '')
                    if os.path.exists(os.path.join(dest, slug + '.html')):
                        rows.append((row[0].strip(), slug))
    li = '\n'.join(f'<li><a href="{s}.html">{n}</a> <code>{s}</code></li>'
                   for n, s in rows)
    open(os.path.join(dest, 'index.html'), 'w', encoding='utf-8', newline='\n').write(
        '<!DOCTYPE html>\n<html lang="ja"><head><meta charset="utf-8">'
        '<title>注釈付き CRF（16.1.2）</title><style>\n'
        'body{font-family:"Hiragino Sans","Yu Gothic UI",Meiryo,Arial,sans-serif;'
        'margin:28px auto;max-width:820px;color:#1a1a1a;line-height:1.7;font-size:15px}\n'
        'h1{font-size:1.1rem}a{color:#004a95}code{background:#eef0f2;padding:1px 5px;'
        'border-radius:4px;font-size:.82em;color:#555}ol{padding-left:1.6em}li{margin:3px 0}\n'
        '</style></head><body>\n<h1>注釈付き CRF（16.1.2）</h1>\n'
        f'<p>{len(rows)} 帳票。CRF の記入順に並べています。帳票の中の項目には '
        'SDTM の変数が注釈されています。</p>\n<ol>\n' + li +
        '\n</ol>\n<p><a href="../traceability.html">トレーサビリティ索引へ戻る</a>　'
        '<a href="../README.html">最初のページへ戻る</a></p>\n</body></html>\n')
    return len(rows)


def acrf_source(box, given, refresh):
    """aCRF の写しの置き場所を返す。

    S3 から毎回落とすと網に依存し、落ちた帳票だけ欠けた配布物ができ得る。Box に写しを
    1つ持ち（input/acrf）、パッケージはそこから写す。作業用の索引（output/deliver/r/traceability.html）
    も同じ写しを相対パスで見るので、写しが aCRF のローカル正本になる。
    """
    if given:
        return given, []
    d = os.path.join(box, 'input', 'acrf')
    have = glob.glob(os.path.join(d, '*.html'))
    if have and not refresh:
        print(f'  aCRF: Box の写しを使う（{len(have)} 帳票・{d}）')
        return d, []
    if os.path.isdir(d):
        # 作り直すときは消してから作る。CSS はファイル名に digest が入っており、
        # 残っていると同じ名前で取り直さないため、古い実体が残る
        shutil.rmtree(d)
    n, ng = fetch_acrf(d)
    print(f'  aCRF: S3 から写しを作った（{n} 帳票・{d}）')
    return d, ng


NARR_INDEX = '''<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<title>重篤な有害事象の経過（14.3.3）</title><style>
body{font-family:"Hiragino Sans","Yu Gothic UI",Meiryo,Arial,sans-serif;margin:28px auto;
max-width:820px;color:#1a1a1a;line-height:1.7;font-size:15px}
h1{font-size:1.1rem}a{color:#004a95}code{background:#eef0f2;padding:1px 5px;border-radius:4px;
font-size:.82em;color:#555}ul{padding-left:1.5em}li{margin:3px 0}p{margin:6px 0}
.note{background:#fdf3f3;border-left:4px solid #8a1c1c;padding:9px 13px;font-size:.9rem}
</style></head><body>
<h1>重篤な有害事象の経過（14.3.3）</h1>
<p>SAE 報告書の経過内容を読み物にしたものです（__NEV__件・__NSUB__症例）。施設が CRF へ
入力した日本語の自由記述で、原文の文字は変えていません。</p>
<div class="note">外部への提供（データ共有プラットフォームへの登録を含む）の対象外です。
解析には使わないため、SDTM・ADaM のデータセットと define.xml には含めていません。
被験者の身体的所見・受診日・治療の詳細が原文のまま入っています。</div>
<ul>
<li><a href="sae_narratives.html">経過（索引つき・__NEV__件）</a></li>
</ul>
<p>各事象は <code>AESPID</code>（SAE 報告書の番号）で SDTM の <code>AE</code> と対応します。
同じ事象の集計は<a href="../14_tlf/ja/T_5_4_8.html">表 5.4.8 重篤な有害事象</a>です。</p>
<p><a href="../README.html">最初のページへ戻る</a></p>
</body></html>
'''


def copy_narratives(box, dest):
    """SAE の経過記述（E3 14.3.3）を写して、節の説明を1枚添える。

    経過記述は施設が CRF の SAE 報告書へ入力した日本語の自由記述で、解析には使わないため
    SDTM・ADaM・define.xml・共有パッケージには載せていない（docs/spec/sdtm-spec.md 3.16）。
    PI へは読み物として渡すので、E3 が「死亡・その他の重篤な有害事象の記述」を置く 14.3.3
    に入れる。外部提供の対象外である旨は、この節の説明と README の両方に出す。
    """
    cand = sorted(glob.glob(os.path.join(box, 'output', 'pv',
                                         boxpath.trial_id() + '_sae_narratives_*.html')))
    if not cand:
        print('  14_3_3_narratives: 経過記述の HTML が無いので入れない'
              '（Rscript scripts/build-sae-narratives.R で作る）')
        return 0, 0, 0
    src = cand[-1]                     # 名前に日付が入るので最新を採る
    t = open(src, encoding='utf-8', errors='replace').read()
    n_ev = t.count('<div class="case" id=')
    m = re.search(r'(\d+)件（(\d+)症例）', t)
    n_sub = int(m.group(2)) if m else 0
    # 経過記述の中に URL 様の文字列があると検査が外部 URL として拾う。原文の文字は変えない
    # 方針なので書き換えず、件数だけ知らせる（検査には WARN として出る）
    n_url = len(re.findall(r'https?://', t))
    if n_url:
        print(f'  14_3_3_narratives: 本文に URL 様の文字列が {n_url} 件ある'
              '（原文は変えないため検査の WARN として出る）')
    # 他の節と同じで、どのページからも入口へ戻れるようにする
    t = t.replace('</body>',
                  '<p class="meta"><a href="index.html">この節の説明へ戻る</a>\u3000'
                  '<a href="../README.html">最初のページへ戻る</a></p>\n</body>')
    os.makedirs(dest, exist_ok=True)
    open(os.path.join(dest, 'sae_narratives.html'), 'w', encoding='utf-8',
         newline='\n').write(t)
    open(os.path.join(dest, 'index.html'), 'w', encoding='utf-8',
         newline='\n').write(
        NARR_INDEX.replace('__NEV__', str(n_ev)).replace('__NSUB__', str(n_sub)))
    print(f'  14_3_3_narratives: 経過記述 {n_ev} 件（{n_sub} 症例）と節の説明 1')
    return 2, n_ev, n_sub


README = '''<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><title>__TRIAL__ 解析パッケージ</title>
<style>
body{font-family:"Hiragino Sans","Yu Gothic UI",Meiryo,Arial,sans-serif;margin:28px auto;
max-width:860px;color:#1a1a1a;line-height:1.7;font-size:15px}
h1{font-size:1.15rem}h2{font-size:.98rem;margin:24px 0 6px;border-bottom:2px solid #004a95;
padding-bottom:4px}a{color:#004a95}code{background:#eef0f2;padding:1px 5px;border-radius:4px;
font-size:.86em}ul{margin:6px 0}li{margin:2px 0}p{margin:6px 0}
.big{display:inline-block;background:#004a95;color:#fff;padding:8px 16px;border-radius:6px;
text-decoration:none;font-weight:600;margin:6px 8px 6px 0}
.note{background:#fffbe6;border-left:4px solid #f0c000;padding:9px 13px;font-size:.9rem}
</style></head><body>
<h1>__TRIAL__ 解析パッケージ __DATE__</h1>
<p><a class="big" href="traceability.html">トレーサビリティ索引をひらく</a>
<a class="big" href="14_tlf/ja/__FIRST__">図表をひらく</a>
<a class="big" href="16_1_2_acrf/index.html">CRF をひらく</a></p>

<h2>何が入っているか</h2>
<p>階層は ICH E3（総括報告書の構成）の番号に合わせてあります。</p>
<ul>
<li><code>14_tlf/</code> … 図表。<code>ja/</code> と <code>en/</code> に1図表=1ファイルの HTML、
    通し読み用の HTML、言語ごとの Excel（1図表=1シート）。図表ごとの HTML には言語の
    切り替えと、トレーサビリティ索引・解析・ADaM 変数へのリンクがあります。Excel は
    数値をそのまま扱えるようにしたもので、生存時間曲線はシート上のデータ範囲を参照する
    チャートなので、値や体裁を Excel の中で調節できます</li>
__NARR__
<li><code>16_1_2_acrf/</code> … 注釈付き CRF（__NACRF__帳票）。
    <a href="16_1_2_acrf/index.html">目次</a>から帳票を選べます。項目ごとに錨があり、
    トレーサビリティ索引から該当の入力欄へ直接飛びます</li>
<li><code>16_1_9_methods/</code> … 統計手法の記録。define.html（SDTM・ADaM）と各仕様の
    HTML（<a href="16_1_9_methods/sdtm-spec.html">SDTM 作成仕様</a>・
    <a href="16_1_9_methods/adam-spec.html">ADaM 作成仕様</a>・
    <a href="16_1_9_methods/ars-spec-index.html">ARS 解析仕様</a>ほか）。
    トレーサビリティ索引の「仕様書」欄から該当の節へ直接飛びます</li>
<li><code>data/ard/</code> … 図表の元になった結果値（ARD）。集計値で被験者単位ではありません</li>
<li><code>reproduce/</code> … R 一式。図表まで作り直せます</li>
__SUBJ__
</ul>

<h2>どう辿るか</h2>
<p>トレーサビリティ索引は、CRF の入力欄・SDTM のレコードと変数・ADaM 変数・解析・図表を1本の鎖として
縦に並べます。上から下がデータの流れる向きです。行を押すとその段で選べるものが出て、
1つ選ぶと決まる範囲は自動で埋まります。決まらない段は候補の件数を出して選択を待ちます。</p>
<p>図表からも遡れます。図表の HTML の下にある「トレーサビリティ索引でこの図表を辿る」から索引の該当位置が
開き、そこから ADaM・SDTM・CRF へ下れます。</p>

<h2>作り直すには</h2>
<p><code>reproduce/</code> に R のプログラムと仕様ファイルが入っています。R 4.2 以降で
動きます。依存は <code>readr</code>・<code>dplyr</code>・<code>survival</code>・
<code>jsonlite</code>・<code>haven</code> で、使った版は <code>renv.lock</code> にあります。
<code>reproduce/</code> を起点に R を開き、最初に一度だけ次を実行すると同じ版が揃います。</p>
<ul>
<li><code>renv::restore()</code></li>
</ul>
<p>その後、次の順に実行します。</p>
<ul>
<li><code>__TRIAL___CSVtoSDTM.R</code> → <code>__TRIAL___SDTMtoADaM.R</code>
    → <code>__TRIAL___ARD.R</code> → <code>__TRIAL___TLF.R</code></li>
</ul>
<div class="note">被験者単位のデータ（受領CSV・SDTM・ADaM・一覧）は__SUBJNOTE__</div>

<h2>数値の出どころ</h2>
<p>図表の数値は ARD（1行が1つの結果値）から作っています。ARD は SAS系と R系で二重に作り、
解析ID・水準・統計量をキーに突き合わせています。図表そのものも両系統で描いてセル単位で
比べており、突合の結果は <code>16_1_9_methods/</code> の記録にあります。</p>
</body></html>
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', help='パッケージを作る場所（既定は Box の output/deliver/r/）')
    ap.add_argument('--with-subject-data', action='store_true',
                    help='被験者単位のデータ（SDTM・ADaM・受領CSV・一覧）も入れる')
    ap.add_argument('--acrf-dir', help='aCRF を取得済みのフォルダから写す（S3 へ行かない）')
    ap.add_argument('--refresh-acrf', action='store_true',
                    help='Box の aCRF の写し（input/acrf）を S3 から作り直す')
    a = ap.parse_args()

    box = boxpath.trial_dir()
    out = box if not a.out else a.out
    day = datetime.date.today().strftime('%Y%m%d')
    # 納品パッケージは output/deliver/<実装系統>/ に置く。図表は R 系を納品するので r。
    # 方針の正本は nnh/trial-planning-and-analysis の pipeline/analysis-pipeline-plan.md
    pkg = os.path.join(a.out if a.out else os.path.join(box, 'output', 'deliver', 'r'),
                       boxpath.trial_id() + f'_PI_{day}')
    if os.path.exists(pkg):
        shutil.rmtree(pkg)
    os.makedirs(pkg)
    print(f'{pkg} を作る')

    # 以前の版は 旧版/ へ退避する。直下に最新の1組だけを置いて、どれが最新かを一目で
    # 分かるようにする（削除ではない）。check-pi-package.py は直下だけを見る
    base_dir = os.path.dirname(pkg)
    arc = os.path.join(base_dir, '旧版')
    moved = 0
    for p in sorted(glob.glob(os.path.join(base_dir, boxpath.trial_id() + '_PI_*'))):
        if os.path.abspath(p) == os.path.abspath(pkg) or not os.path.isdir(p):
            continue
        os.makedirs(arc, exist_ok=True)
        dst = os.path.join(arc, os.path.basename(p))
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.move(p, dst)
        moved += 1
    if moved:
        print(f'  以前の版 {moved} 件を {arc} へ退避した')

    # --- 14章 図表 ---
    n_fig = {}
    for lang in ('ja', 'en'):
        src = os.path.join(box, 'output', 'tlf', 'r-' + lang)
        if not os.path.isdir(src):
            sys.exit(f'{src} が無い。先に Rscript program/r/{boxpath.trial_id()}_TLF.R を回す。')
        # 図表ごとの HTML だけを拾う。同じディレクトリに通し読み HTML も置くため
        n_fig[lang] = (copy_tlf(src, os.path.join(pkg, '14_tlf', lang), 'T_*.html')
                       + copy_tlf(src, os.path.join(pkg, '14_tlf', lang), 'F_*.html'))
    n_doc = n_xl = 0
    docs = []
    for lang in ('ja', 'en'):
        d = os.path.join(box, 'output', 'tlf', 'r-' + lang)
        docs += glob.glob(os.path.join(d, boxpath.trial_id() + '_TLF_*_r.html'))
        # Excel（言語ごとに1ブック、図表ごとに1シート）。研究者が数値をそのまま扱え、
        # 生存時間曲線はブック内のデータ範囲を参照するチャートなので図も調節できる
        docs += glob.glob(os.path.join(d, boxpath.trial_id() + '_TLF_*_r.xlsx'))
    for p in sorted(docs):
        # 配布物の名前から実装系統の印（_r）を落とす
        base = os.path.basename(p).replace('_r.', '.')
        copy(p, os.path.join(pkg, '14_tlf', base))
        if base.endswith('.xlsx'):
            n_xl += 1
        else:
            n_doc += 1
    print(f'  14_tlf: 図表ごと ja {n_fig["ja"]} / en {n_fig["en"]}、'
          f'通し読み {n_doc}、Excel {n_xl}')

    # --- 14.3.3 重篤な有害事象の経過（narratives） ---
    n_nar, n_ev, n_sub = copy_narratives(box, os.path.join(pkg, '14_3_3_narratives'))
    narr = ('<li><code>14_3_3_narratives/</code> … 重篤な有害事象の経過（narratives）。'
            f'{n_ev}件・{n_sub}症例。'
            '<a href="14_3_3_narratives/index.html">この節の説明</a>から開きます。'
            '施設が CRF へ入力した自由記述が原文のまま入っており、外部への提供'
            '（データ共有プラットフォームへの登録を含む）の対象外です</li>') if n_nar else ''

    # --- 16.1.2 注釈付き CRF ---
    src, ng = acrf_source(box, a.acrf_dir, a.refresh_acrf)
    dst = os.path.join(pkg, '16_1_2_acrf')
    shutil.copytree(src, dst, dirs_exist_ok=True)
    n_acrf = len(glob.glob(os.path.join(dst, '*.html')))
    write_acrf_index(dst)
    print(f'  16_1_2_acrf: {n_acrf} 帳票' + (f'（取得できず {ng}）' if ng else ''))

    # --- 16.1.9 統計手法の記録 ---
    m = os.path.join(pkg, '16_1_9_methods')
    n_m = 0
    for src, dst, lay in ((os.path.join(box, 'datasets', 'sas', 'sdtm', 'define.html'),
                           'define_sdtm.html', 'sdtm'),
                          (os.path.join(box, 'datasets', 'sas', 'adam', 'define.html'),
                           'define_adam.html', 'adam')):
        if os.path.exists(src):
            # define.html はデータセット（Dataset-JSON）へ隣のファイルとしてリンクしている。
            # パッケージでは data/<層>/ に置くので相対パスを差し替える。被験者単位データを
            # 入れない配布ではファイルごと無いので、リンクを外して名前だけ残す。
            t = open(src, encoding='utf-8', errors='replace').read()
            if a.with_subject_data:
                t = re.sub(r'href="([a-z0-9_]+\.json)"',
                           lambda x: f'href="../data/{lay}/{x.group(1)}"', t)
            else:
                t = re.sub(r'<a[^>]*href="[a-z0-9_]+\.json"[^>]*>(.*?)</a>', r'\1', t,
                           flags=re.S)
            # define.xml は注釈付き CRF を blankcrf.pdf として指す。ここでは帳票ごとの
            # HTML を同梱しているので目次へ向ける。同梱しない補助資料へのリンクは外す。
            t = t.replace('href="blankcrf.pdf"', 'href="../16_1_2_acrf/index.html"')
            t = re.sub(r'<a[^>]*href="[^"]*\.pdf"[^>]*>(.*?)</a>', r'\1', t, flags=re.S)
            os.makedirs(m, exist_ok=True)
            open(os.path.join(m, dst), 'w', encoding='utf-8', newline='\n').write(t)
            n_m += 1
    # 仕様は md ではなく HTML で入れる。節ごとに id があるので、トレーサビリティ索引の「仕様書」欄から
    # 該当節へ直接飛べる。正本は docs の md で、この HTML は build-spec-html.py が作る派生物。
    # 索引の生成より前に作る（索引は同梱した HTML の節の id を読んでリンクを決める）
    before = set(glob.glob(os.path.join(m, '*.html')))
    sh(sys.executable, os.path.join(SCRIPTS, 'build-spec-html.py'), '--out-dir', m, '--quiet')
    n_m += len(set(glob.glob(os.path.join(m, '*.html'))) - before)
    for p in sorted(glob.glob(os.path.join(box, 'output', 'compare', 'tlf_compare_*.csv'))):
        copy(p, os.path.join(m, os.path.basename(p)))
        n_m += 1
    # ARS の ReportingEvent。解析の定義と結果値が CDISC の標準形式で1つに入っている。
    # ARS を入力とするツール（TFL Designer 等）に載せられ、将来の再利用にも効く。
    # 被験者単位の情報は含まない（集計値のみ）。docs/spec/ars-migration-plan.md。
    for sysname in ('sas', 'r'):
        src = os.path.join(box, 'datasets', sysname, 'ard',
                           f'reporting-event-{sysname}.json')
        if os.path.exists(src):
            copy(src, os.path.join(m, os.path.basename(src)))
            n_m += 1
    print(f'  16_1_9_methods: {n_m} ファイル')

    # --- data（ARD は集計値なので既定で入れる） ---
    n_d = 0
    for name in ('ard_cards.csv', 'ard_cards_r.csv'):
        p = os.path.join(box, 'datasets', 'sas', 'adam', name)
        if os.path.exists(p):
            copy(p, os.path.join(pkg, 'data', 'ard', name))
            n_d += 1
    print(f'  data/ard: {n_d} ファイル')

    # --- reproduce（R 一式と仕様ファイル） ---
    n_r = copy_tree(os.path.join(REPO, 'program', 'r'), os.path.join(pkg, 'reproduce'), '*.R')
    # 版の固定。lock だけでなく renv の活性化2ファイルも入れる。配った先で reproduce/ を
    # 起点に R を開くと renv が自分を取ってきて .libPaths を差し替えるので、
    # renv::restore() だけで lock と同じ版が揃う（PI に renv の導入手順を要求しない）
    copy(os.path.join(REPO, 'renv.lock'), os.path.join(pkg, 'reproduce', 'renv.lock'))
    copy(os.path.join(REPO, '.Rprofile'), os.path.join(pkg, 'reproduce', '.Rprofile'))
    copy(os.path.join(REPO, 'renv', 'activate.R'),
         os.path.join(pkg, 'reproduce', 'renv', 'activate.R'))
    # 機械が読む定義の正本は docs/metadata/。配布形態では input/spec/ へ平らに写す
    # （R 側は ap_spec() が両方を探す）
    # trial.json は R が起動時に読む（試験の識別子と Box の中の置き場）。同梱しないと
    # 配った先で図表の描画が「trial.json が見つかりません」で止まる（2026-08-29）
    for name in ('trial.json',
                 'tlf-index.csv', 'label-catalog.csv', 'variable-map.csv',
                 'crf-field-map.csv', 'crf-option-map.csv',
                 'reference-table-rows.csv', 'reference-values.csv',
                 'mr-timepoint.csv'):
        copy(os.path.join(REPO, 'docs', 'metadata', name),
             os.path.join(pkg, 'reproduce', 'input', 'spec', name))
    for name in ('ta.csv', 'te.csv', 'ti.csv', 'ts.csv', 'tv.csv'):
        copy(os.path.join(REPO, 'docs', 'metadata', 'trial-design', name),
             os.path.join(pkg, 'reproduce', 'input', 'spec', name))
    # R のコメントは仕様書を `docs/<名前>.md` で指す。R を回す起点が reproduce/ なので、
    # その直下に docs/ を置けば配った先でも同じ相対パスで辿れる（16_1_9_methods の HTML は
    # 読み物としての同じ内容で、正本はこの md。CLAUDE.md「文書の正本」）。同梱するものは
    # R の中身から集める。一覧を別に持つとコメントを直したときにズレるため。
    # 同梱した md が指す md も辿る。`docs/spec/adam-spec.md` は時間イベントの導出とデータセットの
    # 構成の正本として `docs/tmf/spec/efs_plan_v0.5.md`・`analysis_plan_v0.2.md` を指しており、
    # 同梱しないとパッケージの中で参照先が無くなる（2026-08-23 に納品対象へ加えると決めた）。
    # 参照の書き方は本文中の `docs/<パス>.md` と md のリンク `](<パス>.md)` の2通りある。
    n_doc, lost, blocked = 0, [], []

    def md_refs(text, here):
        """docs からの相対パスの一覧を返す。

        R のコメントは `docs/<パス>.md` と書く（docs からの相対）。md 同士のリンクは
        `](<パス>.md)` で、そのファイルのあるフォルダからの相対なので、docs からの
        相対へ直してから辿る（docs を階層化したので両者が一致しない）。
        """
        out = [x.lstrip('./') for x in re.findall(r'docs/([\w.\-/]+\.md)', text)]
        if here is not None:
            for x in re.findall(r'\]\(([\w.\-/]+\.md)\)', text):
                out.append(os.path.normpath(os.path.join(here, x)).replace(os.sep, '/'))
        return out

    pending = []
    for p in sorted(glob.glob(os.path.join(pkg, 'reproduce', '*.R'))):
        pending += md_refs(open(p, encoding='utf-8', errors='replace').read(), None)
    seen = set()
    while pending:
        name = pending.pop(0).lstrip('./')
        if name in seen:
            continue
        seen.add(name)
        if not doc_allowed(name):
            blocked.append(name)
            continue
        src = os.path.join(REPO, 'docs', name)
        if not os.path.exists(src):
            lost.append(name)
            continue
        dst = os.path.join(pkg, 'reproduce', 'docs', name)
        body = open(src, encoding='utf-8', errors='replace').read()
        if not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            # 同梱しない md へのリンクは外してから写す。残すとパッケージの中で
            # 参照先が無くなり、check-pi-package.py が落ちる
            open(dst, 'w', encoding='utf-8', newline='\n').write(
                drop_links(body, os.path.dirname(name)))
            n_doc += 1
        pending += md_refs(body, os.path.dirname(name))
    # 同梱しなかった参照は報告するが、これは異常ではない。akiko-office の環境文書
    # （`methods/…`・`sas-environment.md` など）とリポジトリルートの作業記録
    # （`action-items.md`）は納品対象外なので、docs/ に無いのが正しい
    if blocked:
        print(f'  納品対象外の文書 {len(blocked)} 件を外した（リンクは本文の文字列へ落とした）: '
              + '、'.join(sorted(set(blocked))))
    print(f'  reproduce: R {n_r} 本 + 仕様 13 ファイル + docs {n_doc} ファイル'
          + (f'（同梱しなかった参照 {len(set(lost))} 件: {sorted(set(lost))}）' if lost else ''))

    # --- 被験者単位のデータ（明示の指定があるときだけ） ---
    subj = ''
    if a.with_subject_data:
        c = 0
        for lay, src in (('sdtm', os.path.join(box, 'datasets', 'sas', 'sdtm', 'json')),
                         ('adam', os.path.join(box, 'datasets', 'sas', 'adam', 'json'))):
            if os.path.isdir(src):
                c += copy_tree(src, os.path.join(pkg, 'data', lay), '*.json')
        for src, dst in ((os.path.join(box, 'input', 'rawdata'),
                          os.path.join(pkg, 'reproduce', 'input', 'rawdata')),
                         (os.path.join(box, 'input', 'ext'),
                          os.path.join(pkg, 'reproduce', 'input', 'ext'))):
            if os.path.isdir(src):
                c += copy_tree(src, dst, '*.csv')
        os.makedirs(os.path.join(pkg, '16_2_listings'), exist_ok=True)
        print(f'  被験者単位データ: {c} ファイル（--with-subject-data）')
        subj = ('<li><code>data/sdtm</code>・<code>data/adam</code>・'
                '<code>reproduce/input</code> … 被験者単位のデータ（取り扱いに注意）</li>')

    # --- トレーサビリティ索引（相対パスを E3 の階層に合わせて作り直す） ---
    o = sh(sys.executable, os.path.join(SCRIPTS, 'build-traceability.py'),
           '--out', os.path.join(pkg, 'traceability.html'),
           '--acrf-base', '16_1_2_acrf', '--tlf-base', '14_tlf/ja')
    for line in (o or '').splitlines():
        if line.startswith(('aCRF:', '図表:', '  同梱')):
            print('  ' + line)

    # --- README ---
    first = sorted(os.listdir(os.path.join(pkg, '14_tlf', 'ja')))[0]
    html = (README.replace('__TRIAL__', boxpath.trial_id())
            .replace('__DATE__', datetime.date.today().strftime('%Y-%m-%d'))
                  .replace('__FIRST__', first)
                  .replace('__NACRF__', str(n_acrf))
                  .replace('__NARR__', narr)
                  .replace('__SUBJ__', subj)
                  .replace('__SUBJNOTE__', '同梱しています。取り扱いに注意してください。'
                           if a.with_subject_data else
                           'この配布物には入っていません。必要な場合は別途お知らせください。'))
    open(os.path.join(pkg, 'README.html'), 'w', encoding='utf-8', newline='\n').write(html)

    tot = sum(len(f) for _, _, f in os.walk(pkg))
    size = sum(os.path.getsize(os.path.join(r, f))
               for r, _, fs in os.walk(pkg) for f in fs)
    print(f'できた: {pkg}（{tot} ファイル・{size / 1e6:.1f} MB）')

    # フォルダごとどこへ置いても動くか（相対リンクだけで閉じているか）をその場で確かめる
    print('--- 自己完結の検査 ---')
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'check-pi-package.py'), pkg],
                       capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    print((r.stdout or '').rstrip())
    if r.returncode:
        print((r.stderr or '')[-1000:])
        sys.exit('パッケージの中にパッケージ外を指すリンクがある')


if __name__ == '__main__':
    main()
