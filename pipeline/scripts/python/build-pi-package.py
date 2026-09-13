# build-pi-package.py
#
# PI へ渡す一式を1つのフォルダへ組み立てる。手で集めると版が混ざるため必ずこれを通す。
#
# 階層は ICH E3（総括報告書の構成）の番号を骨格にする。14章が本文から参照する図表、
# 16.1.2 が CRF の見本、16.1.9 が統計手法の記録、16.2 が被験者データ一覧。重篤な有害事象の
# 経過（narratives）は E3 が 14.3.3 に置くものなので 14_3_3_narratives へ入れる。トレーサビリティ索引は
# E3 の構成要素ではないのでルート直下に置き、相対パスで 14章と 16.1.2 を参照する。
# 設計の正本は docs/reporting/traceability-design.md の「PI 向けパッケージ」。
#
#   <試験ID>_PI_YYYYMMDD/
#     README.html                    入口
#     manifest.csv ・ manifest.html   同梱物の一覧（相対パス・バイト数・SHA-256）
#     traceability.html              トレーサビリティ索引（14_tlf と 16_1_2_acrf を相対で参照）
#     14_tlf/index.html              図表の一覧（JavaScript を使わずに開ける静的な目次）
#     14_tlf/ja/<表番号>.html         図表ごと（日本語。索引が既定で指す）
#     14_tlf/en/<表番号>.html         図表ごと（英語）
#     14_tlf/<言語>/figures/<図番号>.svg  図のベクター形式（論文へ出すとき HTML から取り出さずに済む）
#     14_tlf/*.html                  通し読み用
#     14_tlf/*.xlsx                  言語ごとに1ブック（1図表=1シート。KM はネイティブなチャート）
#     14_3_3_narratives/             重篤な有害事象の経過（研究責任医師向けの読み物）
#     16_1_2_acrf/<帳票>.html         注釈付き CRF 62帳票（#fieldNN の錨つき）
#     16_1_9_methods/                define.html（SDTM・ADaM）と仕様の HTML（節に錨つき）
#     16_1_9_methods/validation-report.html   検証の記録（リンク検査・索引の整合・適合性検査の仕分け）
#     16_1_9_methods/double-coding-report.html 二重作成の突合の結果と合否
#     data/ard/                      ARD（集計値。被験者単位ではない）
#     reproduce/                     解析を走らせ直す一式。並びは解析側のリポジトリと同じ
#     reproduce/README.html          再現の手順（入力・実行の順・成功の判定・つまずいたとき）
#     reproduce/program/r/           R 一式
#     reproduce/scripts/             索引・ReportingEvent・define.xml を作り直す Python 一式
#     reproduce/docs/                仕様（md）と、プログラムが読む宣言・受入基準・試験の設定
#     16_2_listings/ ・ data/sdtm ・ data/adam ・ reproduce/input   ... 被験者単位データ（必ず入れる）
#
# 被験者単位のデータは区分けを設けず必ず入れる（2026-08-30 の判断。C2-073）。実行できる形で
# 入れるのは R と Python だけにする。研究責任医師の環境に SAS が無く、SAS のプログラムと
# 実行ログを渡しても動かせないためで、二重に作った事実は突合の結果と合否で示す。
#
# 使い方
#   python scripts/build-pi-package.py                      ... Box の output/ へ作る
#   python scripts/build-pi-package.py --out <dir>          ... 置き場所を指定
#   python scripts/build-pi-package.py --acrf-dir <dir>     ... aCRF を取得済みのフォルダから写す
import sys, os, re, csv, glob, gzip, json, shutil, hashlib, argparse, datetime, tempfile, subprocess
import urllib.request, urllib.parse, concurrent.futures, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

NL = chr(10)   # 生成する HTML・CSV の改行。Windows でも LF に揃える
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, 'scripts')
ACC = 'validation/acceptance'    # 機械が読む受入基準の置き場（docs からの相対）
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
# output/tlf/traceability.html を見る形）で書かれている。パッケージでは索引が直下、
# 図表が 14_tlf/<言語>/ なので、写すときに書き換える。図表を2度描かずに済ませるため、
# 書き換えはここ1箇所に閉じる（作業用の並びは TLF.R の IX と言語間リンクが正本）。
TLF_LINK_FIX = [('../traceability.html', '../../traceability.html'),
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
# 許可はファイル単位で決める。ディレクトリごと許可すると、そのディレクトリへ文書を足した
# 時点で、その文書が納品物へ黙って入る。spec も tmf も内部の設計記録や作業計画を含み得るので、
# records と同じく名前を挙げた分だけを入れる（2026-08-30 にディレクトリ許可からファイル許可へ
# 変えた）。既定は「入れない」で、挙げていない文書を指す参照は組み立てのたびに一覧で報告する。
#
# 挙げてよいのは、結果の値がなぜそうなるかを説明する文書に限る。内部の品質管理・環境の
# 検証・作業中の指示は、PI が読む前提で書かれていないので入れない。
#
# ここは reproduce/docs へ写す md の境界である。16_1_9_methods へ HTML で入れる仕様の一覧は
# build-spec-html.py の FILES が持つ（読み物として節に錨を付ける対象で、目的が違う）。
DOCS_ALLOWED = {
    # 実装が従う仕様
    'spec/sdtm-spec.md',                                # SDTM 作成仕様
    'spec/adam-spec.md',                                # ADaM 作成仕様
    'spec/ard-spec.md',                           # ARD 解析仕様
    'records/analysis-population-derivation.md',           # 解析対象集団の判定
    'validation/ard-double-coding-spec.md',                   # 二重作成の突合の仕様
    'validation/quality-assurance.md',                        # 品質の担保のまとめ
    # 外部入力の仕様は疾患ごとに中身が変わるので、その試験のリポジトリでここへ足す
    'validation/ard-double-coding-spec.md',  # R 系の実装仕様
    'reporting/traceability-design.md',            # 表示名と索引の設計
    'spec/tlf-spec.md',                   # 図表の宣言の設計
    'reporting/csr-section-map.md',                          # CSR 第14章と図表番号の対応
    'reporting/statistical-methods-and-results.md',          # 統計手法と結果の記述
    'reporting/analysis-limitations.md',                     # 解析の前提と限界（README の元）
    'decisions/data-handling-decisions.md',                  # データの取り扱いの決定
    'decisions/identifier-naming-rule.md',                   # 識別子の命名規則
    'reporting/reference-values-source.md',                  # 基準値の出典
    'validation/tte-variable-specification.md',               # 時間イベント変数の仕様
    # 主要評価項目の導出仕様は名前がエンドポイントごとに違うので、その試験で足す
    # 規制文書（固定した計画）。研究計画書はファイル名に版が入るので、その試験で足す
    'records/analysis-dataset-design.md',                        # 解析計画
    # 結果の値の根拠になる調査の記録。その試験で行った調査の名前は試験ごとに違う
    'validation/records/sdtm-conformance-findings-20260815.md',    # 適合性検証の結果と仕分け
    'records/rawdata-value-scan-20260809.md',           # 受領データの実値の走査
    'records/ecrf-reference-field-issue-20260809.md',   # eCRF の不具合（データの制約）
    'records/dscat-disposition-event-note.md',          # 観察終了の扱い
    'records/ars-migration-20260829.md',                # ARS 準拠へ移った経緯と到達点
}


def doc_allowed(name):
    """docs からの相対パスが納品してよいものか"""
    return name.replace(os.sep, '/').lstrip('./') in DOCS_ALLOWED


# 固定版 SAP（PDF）。この解析が従った統計解析計画で、規制文書としての版管理の正本である。
# 同梱する実装仕様（解析用データセット設計など）とは性質が違う。
# 置き場は解析が使う Box の試験フォルダ（boxpath.trial_dir()）ではなく、試験管理側の
# 別のツリーなので試験フォルダからは解決できない。試験ごとに変わる値なのでコードへ書かず、
# 他の試験固有の値と同じ docs/metadata/trial.json が持つ（boxpath.config() が読む）。
#
#   "sap_pdf": {"path": ["<試験管理側のフォルダ>", ..., "<SAP の PDF のファイル名>"],
#               "fixed": "YYYY-MM-DD",
#               "box_account": "<box-<環境> ラッパーの環境名>"}
#
# この解析が従った規定そのものなので、欠けたまま渡すと結果値の根拠が一式の中で辿れない。
# Box の同期先が端末によって違って解決できないときは、同梱を飛ばさず組み立てを止める
# （C3-305。以前は警告だけで通していた＝C2-096）。止めれば、原本を解決できる端末で
# 組み直すか、置き場の指定を直すかのどちらかを必ず選ぶことになる。設定そのものが無い
# ときも同じで、黙って SAP 抜きの一式を渡さない。
_SAP = boxpath.config().get('sap_pdf') or {}
SAP_PDF_SRC = tuple(_SAP.get('path') or ())
# 配布名は原本のファイル名の空白をアンダースコアへ替えたもの（原本の版表記をそのまま残す）
SAP_PDF_DST = SAP_PDF_SRC[-1].replace(' ', '_') if SAP_PDF_SRC else ''

# README の計画文書の段が出す案内。copy_sap_pdf が欠落で止めるので、同梱してある前提で書く
SAP_LI = (f'<a href="16_1_9_methods/{SAP_PDF_DST}">統計解析計画書'
          + (f'（SAP、{_SAP["fixed"]} 固定）' if _SAP.get('fixed') else '（SAP）')
          + '</a>と')


# 固定版 SAP を持つ Box アカウント（box-<環境> ラッパーの環境名）。試験管理側の Box が
# どの契約にあるかは試験ごとに違うので、置き場と同じく trial.json が持つ。
SAP_BOX_ACCOUNT = _SAP.get('box_account') or ''


def _box_cli():
    """Box CLI の呼び方を決める。使えなければ None を返す。

    ~/bin/box-<環境> のラッパーがあればそれを使う。環境の選択と、選択に失敗したときに
    別アカウントの結果を黙って返さない仕掛けをラッパーが持つためである。無ければ素の
    box に環境を選ばせてから使う（選択に失敗したらここで諦める。同じ理由で、選べない
    まま直前の環境で走らせない）。"""
    if not SAP_BOX_ACCOUNT:
        return None
    w = shutil.which('box-' + SAP_BOX_ACCOUNT)
    if w:
        return [w]
    b = shutil.which('box')
    if not b:
        return None
    r = subprocess.run([b, 'configure:environments:select', SAP_BOX_ACCOUNT],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return None if r.returncode else [b]


def _box_child(cli, parent, name):
    """Box のフォルダ直下を名前で1件引く。(種別, ID)。無ければ (None, None)"""
    r = subprocess.run(cli + ['folders:items', parent, '--json'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        return None, None
    try:
        items = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None, None
    for it in items:
        if it.get('name') == name:
            return it.get('type'), it.get('id')
    return None, None


def _sap_pdf_via_cli(tmp):
    """Box CLI で固定版 SAP を取り、置いた先のパスを返す。取れなければ None。

    Box Drive を同期していない端末でも納品パッケージを組めるようにするための代替経路
    （2026-09-02）。置き場の正本は SAP_PDF_SRC のままで、Drive 経由と同じ組を root から
    順に辿る。フォルダ ID を焼き付けないので、Box 側で作り直されても追随する。"""
    cli = _box_cli()
    if not cli:
        return None
    fid, kind = '0', 'folder'
    for name in SAP_PDF_SRC:
        if kind != 'folder':
            return None
        kind, fid = _box_child(cli, fid, name)
        if not fid:
            return None
    if kind != 'file':
        return None
    r = subprocess.run(cli + ['files:download', fid, '--destination', tmp],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    got = os.path.join(tmp, SAP_PDF_SRC[-1])
    return got if not r.returncode and os.path.isfile(got) else None


def copy_sap_pdf(dest):
    """固定版 SAP を 16_1_9_methods へ写す。写したファイル数を返す

    経路は2つある。Box Drive の同期フォルダ（boxpath.box_root()）を先に見て、無ければ
    Box CLI で取りに行く。どちらも駄目なときだけ止める。以前は Drive だけを見ており、
    Drive を同期していない端末では組み立てそのものができなかった（2026-09-02）。"""
    if not SAP_PDF_SRC:
        sys.exit('固定版 SAP の置き場が docs/metadata/trial.json に無い（sap_pdf.path）。'
                 '必須の同梱物なので組み立てを止める。')
    root = boxpath.box_root()
    src = os.path.join(root, *SAP_PDF_SRC) if root else None
    if src and os.path.isfile(src):
        copy(src, os.path.join(dest, SAP_PDF_DST))
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        got = _sap_pdf_via_cli(tmp)
        if got:
            copy(got, os.path.join(dest, SAP_PDF_DST))
            return 1
    sys.exit('固定版 SAP の PDF が見つからない。必須の同梱物なので組み立てを止める。\n'
             '  Box Drive: ' + os.path.join('<Box>', *SAP_PDF_SRC) + '\n'
             f'  Box CLI  : box-{SAP_BOX_ACCOUNT}（または box + 環境 {SAP_BOX_ACCOUNT}）で'
             '同じ組を root から辿る。環境が無ければ '
             f'box login --default-box-app --name {SAP_BOX_ACCOUNT} で作る')


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



# ICH E3 16.2 の節と、それを埋める ADaM の対応。E3 が挙げる一覧のうち、この試験の ADaM が
# 持つものを割り当てる。16.2.5（個別の有効性データ）は評価項目ごとに分かれるので効果判定と
# 生存時間の2本を置く。対応の正本はここで、索引と README はこれを読む。
E3_162 = [
    ('16.2.1', '中止例', 'adsl', '試験治療の終了理由と観察終了の内訳を持つ'),
    ('16.2.2', '治験実施計画書からの逸脱', 'adsl', 'PPS の判定と除外の理由を持つ'),
    ('16.2.3', '有効性評価から除外された被験者', 'adsl', 'FAS の判定を持つ'),
    ('16.2.4', '人口統計学的データ', 'adsl', '背景因子を持つ'),
    ('16.2.5', '個別の有効性データ（効果判定）', 'adrs', '血液学的・分子遺伝学的効果の判定'),
    ('16.2.5', '個別の有効性データ（生存時間）', 'adtte', '起算日・イベント・打ち切り'),
    ('16.2.6', '有害事象一覧', 'adae', '重篤な有害事象と事前規定項目の Grade'),
    ('16.2.7', '個別の臨床検査値一覧', 'adlb', '臨床検査値'),
    ('16.2.8', '併用薬', 'adcm', '併用薬'),
    ('16.2.8', '曝露', 'adec', 'コースごとの実投与'),
    ('16.2.8', 'バイタルサイン', 'advs', 'バイタルサインと体表面積'),
    ('16.2.8', '既往歴', 'admh', '既往歴'),
]


def write_listings(pkg, box):
    """E3 16.2 の被験者データ一覧。ADaM の Dataset-JSON を CSV へ落として索引を1枚添える。

    HTML の表にすると ADLB のように行数の多いものが開けなくなるので、一覧そのものは CSV に
    して表計算で開けるようにし、HTML は索引だけを持つ。E3 の節との対応は E3_162 が持つ。
    区分けを設けず必ず作る（2026-08-30 の判断。codex-review-2-ledger.md の C2-073）。
    """
    src_dir = os.path.join(box, 'datasets', 'r', 'adam', 'json')
    dest = os.path.join(pkg, '16_2_listings')
    os.makedirs(dest, exist_ok=True)
    made, rows = {}, []
    for sec, title, ds, note in E3_162:
        src = os.path.join(src_dir, ds + '.json')
        if not os.path.isfile(src):
            continue
        if ds not in made:
            d = json.load(open(src, encoding='utf-8-sig'))
            cols = [c['name'] for c in d['columns']]
            with open(os.path.join(dest, ds + '.csv'), 'w',
                      encoding='utf-8-sig', newline='') as f:
                w = csv.writer(f, lineterminator=NL)
                w.writerow(cols)
                for r in d['rows']:
                    w.writerow(['' if v is None else v for v in r])
            made[ds] = (len(d['rows']), len(cols), d.get('label') or ds.upper())
        n, nc, lbl = made[ds]
        rows.append((sec, title, ds, n, nc, lbl, note))
    li = NL.join(
        '<li>{} {} … <a href="{}.csv">{}.csv</a>（{}。{:,} 行 × {} 列。{}）</li>'.format(
            sec, title, ds, ds, lbl, n, nc, note)
        for sec, title, ds, n, nc, lbl, note in rows)
    open(os.path.join(dest, 'index.html'), 'w', encoding='utf-8', newline=NL).write(
        '<!DOCTYPE html>' + NL + '<html lang="ja"><head><meta charset="utf-8">'
        '<title>被験者データ一覧（16.2）</title><style>' + NL +
        'body{font-family:"Hiragino Sans","Yu Gothic UI",Meiryo,Arial,sans-serif;'
        'margin:28px auto;max-width:820px;color:#1a1a1a;line-height:1.7;font-size:15px}' + NL +
        'h1{font-size:1.1rem}a{color:#004a95}ul{padding-left:1.4em}li{margin:5px 0}' + NL +
        '</style></head><body>' + NL + '<h1>被験者データ一覧（16.2）</h1>' + NL +
        '<p>ICH E3 が第16.2章に置く被験者単位の一覧です。中身は解析用データセット（ADaM）'
        'そのもので、表計算で開ける CSV にしてあります。変数の意味は'
        '<a href="../16_1_9_methods/define_adam.html">ADaM の define</a> が持ちます。</p>' + NL +
        '<ul>' + NL + li + NL + '</ul>' + NL +
        '<p><a href="../traceability.html">トレーサビリティ索引へ戻る</a>　'
        '<a href="../README.html">最初のページへ戻る</a></p>' + NL + '</body></html>' + NL)
    return len(made), sum(v[0] for v in made.values())


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
    1つ持ち（input/acrf）、パッケージはそこから写す。作業用の索引（output/tlf/traceability.html）
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
<div class="note">解析には使わないため、SDTM・ADaM のデータセットと define.xml には含めていません。
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
    SDTM・ADaM・define.xml には載せていない（docs/spec/sdtm-spec.md 3.16）。研究責任医師へは
    読み物として渡すので、E3 が「死亡・その他の重篤な有害事象の記述」を置く 14.3.3 に入れる。
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
<p>__OPEN__</p>

<h2>最初に見るもの</h2>
<p>解析データの全体を1枚で見るなら
<a href="16_1_9_methods/analysis-data-reviewers-guide.html">解析データの案内</a>から入ってください。
試験の概要、解析対象集団、データセットの一覧、統計解析計画書からの逸脱、適合性検査の結果、
再現の一式までを、PHUSE の Analysis Data Reviewer’s Guide の様式でまとめてあります。
受領データの側は<a href="16_1_9_methods/study-data-reviewers-guide.html">受領データの案内</a>、
総括報告書へ写す原稿は<a href="16_1_9_methods/csr-deviations.html">総括報告書の原稿</a>にあります。</p>
<p>主要評価項目の決め方は次のとおりです。括弧の中はその決め方の根拠で、研究計画書・統計解析計画書の節、または条文が無い事柄については決定記録を示します。</p>
<ul>
__PRIMARYDEF__</ul>
<p>この決め方に当てはめた結果です。</p>
__PRIMARYRESULT__
<p>同じ数値は次の図表そのものにもあります。図表を読むときはそちらを見てください。</p>
<ul>
__PRIMARYLINK__</ul>

<h2>解析対象集団と症例の流れ</h2>
<p>集団の定義は次のとおりです。各集団の人数と、登録から解析対象までの内訳は下の図表にあります。
判定の手順は<a href="16_1_9_methods/analysis-population-derivation.html">解析対象集団の判定</a>に
書いてあります。</p>
<ul>
__SETS__</ul>
<p>症例の流れを見る図表。</p>
<ul>
__FLOW__</ul>

<h2>解析の前提と限界</h2>
<p>上の結論と、この一式に入っている図表を読むときの前提です。数値の意味はこの範囲で
受け取ってください。詳細はそれぞれの仕様書にあります。</p>
<ul>
__LIMITS__</ul>

<h2>どのデータから作ったか</h2>
<p>__CUT__</p>
<p>追跡期間と各時点の at-risk 数（まだ観察が続いている人数）は、生存曲線の図の下段と、
対応する表の脚注にあります。</p>

<h2>何が入っているか</h2>
<p>階層は ICH E3（総括報告書の構成）の番号に合わせてあります。ただし図表の番号は
E3 の 14.x ではなく統計解析計画書（SAP）の節番号です（<code>T_5_4_1</code> = 表 5.4.1 = SAP 5.4.1）。
解析の仕様・結果値・索引・突合がすべて SAP の節番号でつながっているため、こちらで通しています。
総括報告書を書く段の 14.x との対応は
<a href="16_1_9_methods/csr-section-map.html">CSR 第14章と図表番号の対応</a>にあります。</p>
<ul>
<li><code>14_tlf/</code> … 図表。<code>ja/</code> と <code>en/</code> に1図表=1ファイルの HTML、
    通し読み用の HTML、言語ごとの Excel（1図表=1シート。数値をそのまま扱え、生存時間曲線は
    シート上のデータ範囲を参照するチャートです）。生存時間曲線の図は
    <code>ja/figures/</code>・<code>en/figures/</code> にベクター形式の SVG としても入っており、
    どれだけ拡大しても線と文字が粗くならず、多くの投稿先がこの形式のまま図を受け付けます</li>
__NARR__
<li><code>16_1_2_acrf/</code> … 注釈付き CRF（__NACRF__帳票）。
    <a href="16_1_2_acrf/index.html">目次</a>から帳票を選べます。項目ごとに錨があり、
    トレーサビリティ索引から該当の入力欄へ直接飛びます</li>
<li><code>16_1_9_methods/</code> … 統計手法の記録。define.html（SDTM・ADaM）と各仕様の
    HTML（<a href="16_1_9_methods/sdtm-spec.html">SDTM 作成仕様</a>・
    <a href="16_1_9_methods/adam-spec.html">ADaM 作成仕様</a>・
    <a href="16_1_9_methods/ard-spec.html">ARD 解析仕様</a>ほか）。
    トレーサビリティ索引の「仕様書」欄から該当の節へ直接飛びます</li>
<li>計画の文書 … 性質が2段に分かれます。承認を経た規制文書は
    __SAP__研究計画書（PRT。固定した版を <code>reproduce/docs/tmf/protocol/</code> に入れています）で、
    この解析はこの2つの規定に従っています。これに対して
    <a href="16_1_9_methods/analysis-dataset-design.html">解析用データセット設計</a>は
    承認の対象ではなく、上の規定を実装へ落とすときに行った判断と、規定が及ばない箇所を
    どう扱ったかを記録した実装の仕様です</li>
<li><a href="16_2_listings/index.html"><code>16_2_listings/</code></a> … 被験者データ一覧（ICH E3 16.2）。解析用データセットを表計算で開ける CSV にしたもの</li>
<li><code>data/ard/</code> … 図表の元になった結果値（ARD）。集計値です</li>
<li><code>reproduce/</code> … 図表を作るための R 一式と仕様ファイル、および受領CSVと外部データ。
    __REPRODUCE__<a href="reproduce/README.html">再現の手順</a>が入口です</li>
<li><a href="manifest.html">同梱物の一覧</a> … 全ファイルの相対パス・バイト数・SHA-256。
    機械で読む形は <code>manifest.csv</code> です</li>
<li><a href="16_1_9_methods/quality-assurance.html">解析の品質の担保</a> … 二重に作って
    突き合わせた範囲、不一致の決着のさせ方、機械で検査した項目、独立レビューの状況を
    ひとまとめにしたものです。下の2件はその根拠にあたります</li>
<li><a href="16_1_9_methods/validation-report.html">検証の記録</a> … 索引の到達率と未接続の一覧、
    リンクの検査、適合性検査の指摘とその仕分け</li>
<li><a href="16_1_9_methods/double-coding-report.html">二重作成の突合</a> … SAS系と R系で
    別々に作って突き合わせた結果と合否</li>
__SUBJ__
</ul>

<h2>どう辿るか</h2>
<p>トレーサビリティ索引は、CRF の入力欄・SDTM のレコードと変数・ADaM 変数・解析・図表を1本の鎖として
縦に並べます。上から下がデータの流れる向きです。行を押すとその段で選べるものが出て、
1つ選ぶと決まる範囲は自動で埋まります。決まらない段は候補の件数を出して選択を待ちます。</p>
<p>図表からも遡れます。図表の HTML の下にある「トレーサビリティ索引でこの図表を辿る」から索引の該当位置が
開き、そこから ADaM・SDTM・CRF へ下れます。</p>
<p>索引はすべての段がつながっているわけではありません。どこまで辿れるか（到達率）と、
つながっていない箇所の一覧は<a href="16_1_9_methods/validation-report.html">検証の記録</a>に
あります。索引は JavaScript で動くので、開けないときは
<a href="14_tlf/index.html">図表の一覧</a>から目的の図表を選んでください。</p>

<h2>作り直すには</h2>
<p>受領CSVから図表までを走らせ直すための R 一式と、入力（受領CSV・外部データ・仕様）が
<code>reproduce/</code> に入っています。作成に使った R は __RVER__ です。入力の置き方、
実行の順、期待される出力、作り直したものが納品したものと同じかの確かめ方、つまずいたときの
対処は<a href="reproduce/README.html">再現の手順</a>にまとめてあります。</p>
<p>図表を読むだけであれば、R を入れる必要はありません。</p>

<h2>数値の出どころ</h2>
<p>図表の数値は ARD（1行が1つの結果値）から作っています。ARD は SAS系と R系で二重に作り、
解析ID・水準・統計量をキーに突き合わせています。図表そのものも両系統で描いてセル単位で
比べています。突合の結果と合否は
<a href="16_1_9_methods/double-coding-report.html">二重作成の突合</a>にあります。</p>
<p>ARD は <code>data/ard/</code> にあります（納品する図表は R系なので
<code>ard_cards_r.csv</code>、SAS系は <code>ard_cards.csv</code>）。表計算で開ける CSV です。
図表の1つの数値がどの行かは、次の列で絞り込めます。</p>
<ul>
__ARDKEYS__</ul>
<p>同じ内容を CDISC の標準形式で持つ
<code>16_1_9_methods/reporting-event-r.json</code>（ARS の ReportingEvent）もあり、そちらは
解析の定義（集団・サブセット・手法・群）と結果値が1つのファイルに入っています。</p>
<p>主要評価項目の判定は ReportingEvent の中にはありません。判定は解析結果ではなく解析結果に
対する判断なので、次のファイルが持ちます。ReportingEvent と同じ <code>16_1_9_methods/</code> に
並べてあるので、閾値の宣言・結果値・判定を同じフォルダの中で突き合わせられます。</p>
<ul>
__PRIMARYDECISION__</ul>

<h2>この一式の開き方</h2>
<p>相互のリンクはすべて相対パスなので、フォルダごとどこへ置いても動きます。逆に、
ファイルを1つだけ取り出して開くとリンクが切れます。</p>
<p>Box などの共有ストレージ上でブラウザのプレビュー機能から開くと、JavaScript が止まる、
HTML どうしの行き来ができない、といったことが起こります。その場合は、フォルダ全体を
ダウンロードしてから <code>README.html</code> を開いてください。</p>
<p>図（Kaplan-Meier 曲線など）の軸と文字が出ないときも同じ原因です。図の文字は字形を
図形として埋め込んであり、プレビュー機能はその参照を解決しないことがあります。
ダウンロードしてブラウザで開けば、軸・目盛り・凡例まで出ます（2026-09-11 に実機で確認）。</p>

<h2>略語</h2>
<ul>
<li>CRF … 症例報告書。施設が試験のデータを入力する帳票</li>
<li>aCRF … 注釈付き症例報告書。CRF の各入力欄に、それがデータのどの変数になるかを書き込んだもの</li>
<li>ICH E3 … 治験の総括報告書の構成を定めた国際的な指針。このフォルダの番号（14・16.1.2・16.1.9・16.2）はその章番号</li>
<li>TLF … 表・一覧・図（Tables, Listings, Figures）。報告書に載せる図表のこと</li>
<li>SDTM … 収集したデータを国際標準の形へ並べ替えたもの。CRF の内容をそのまま持つ</li>
<li>ADaM … SDTM から解析用に導出したデータ。解析対象集団のフラグや生存時間などを持つ</li>
<li>ARD … 解析結果データ。1行が図表の1つの数値にあたる</li>
<li>ARS … 解析結果の標準（Analysis Results Standard）。解析の定義と結果値を機械が読める形で持つ</li>
<li>define … データセットと変数の定義書。どの変数が何を表すかを記す</li>
<li>SHA-256 … ファイルの中身から計算する短い値。中身が変わると値が変わるので、同一性の確認に使う</li>
</ul>

<h2 id="contact">問い合わせ先</h2>
__CONTACT__
</body></html>
'''


PAGE_CSS = ('body{font-family:"Hiragino Sans","Yu Gothic UI",Meiryo,Arial,sans-serif;'
            'margin:28px auto;max-width:860px;color:#1a1a1a;line-height:1.7;font-size:15px}\n'
            'h1{font-size:1.15rem}h2{font-size:.98rem;margin:22px 0 6px;'
            'border-bottom:2px solid #004a95;padding-bottom:4px}a{color:#004a95}\n'
            'code{background:#eef0f2;padding:1px 5px;border-radius:4px;font-size:.86em}\n'
            'ul{margin:6px 0}li{margin:2px 0}p{margin:6px 0}\n'
            '.note{background:#fffbe6;border-left:4px solid #f0c000;padding:9px 13px;'
            'font-size:.9rem}\n.n{color:#555;font-size:.86em}\n')


def page(title, body):
    """同梱するページの共通の外枠。体裁を1か所に置く"""
    return ('<!DOCTYPE html>\n<html lang="ja"><head><meta charset="utf-8">'
            f'<title>{title}</title><style>\n{PAGE_CSS}</style></head><body>\n'
            f'{body}\n</body></html>\n')


def meta_rows(name, sub='metadata'):
    """docs 配下の CSV を読む。数値・件数の正本はこの CSV で、写しを持たない。

    `sub` は docs からの相対フォルダ。既定は機械が読む定義の `metadata`、受入基準は
    `validation/acceptance` を渡す（2026-08-31 に3本を metadata から移した）。
    無い CSV は握り潰さず、どのファイルが欠けたかを示して落とす。
    """
    p = os.path.join(REPO, 'docs', *sub.split('/'), name)
    if not os.path.isfile(p):
        sys.exit(f'ERROR: 定義が無い: {p}')
    with open(p, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def tlf_order(pkg):
    """図表の並びと題名。並びは tlf-index.csv の seq、題名は図表 HTML の <title> が持つ。

    どちらも正本がほかにあるので、一覧をこのスクリプトに書かない。宣言に無い図表が
    出ていたら並びの最後へ回す（黙って落とさない）。
    """
    d = os.path.join(pkg, '14_tlf', 'ja')
    have = {os.path.basename(p)[:-5] for p in glob.glob(os.path.join(d, '*.html'))
            if os.path.basename(p) != 'index.html'}
    seq = [r['lblid'] for r in meta_rows('tlf-index.csv')]
    ids = [x for x in seq if x in have] + sorted(have - set(seq))
    out = []
    for i in ids:
        t = open(os.path.join(d, i + '.html'), encoding='utf-8', errors='replace').read(4000)
        m = re.search(r'<title>(.*?)</title>', t, re.S)
        ttl = re.sub(r'\s+', ' ', m.group(1)).strip() if m else i
        # <title> は「T_5_4_1 表 5.4.1 …」の形。番号は別に出すので題名だけを取る
        out.append((i, ttl[len(i):].strip() if ttl.startswith(i) else ttl))
    return out


def primary_ids():
    """主要評価項目の図表の番号。解析IDから tlf-index.csv を引いて表を決め、
    同じ番号の図（`T_5_4_1` に対する `F_5_4_1`）を対にする。対応表を別に持たない。
    """
    pe = {r['item']: r['value'] for r in meta_rows('primary-endpoint.csv', ACC)}
    tab = [r['lblid'] for r in meta_rows('tlf-index.csv')
           if r['analysis_id'] == pe.get('analysis_id', '')]
    return list(tab) + ['F' + t[1:] for t in tab]


def write_tlf_index(pkg, rows, whole, primary):
    """図表の一覧。JavaScript を使わない静的な目次で、索引が開けないときの入口になる"""
    def li(i, t):
        mark = '　<span class="n">主要評価項目</span>' if i in primary else ''
        return (f'<li><a href="ja/{i}.html">{t}</a> <code>{i}</code>'
                f'　<a class="n" href="en/{i}.html">English</a>{mark}</li>')
    body = (f'<h1>図表の一覧（{len(rows)}件）</h1>\n'
            '<p>番号は統計解析計画書の節番号です（表 5.4.1 は解析計画の 5.4.1）。'
            '日本語版を開きます。English は英語版です。</p>\n<ul>\n'
            + '\n'.join(li(i, t) for i, t in rows) + '\n</ul>\n'
            + ('<h2>通し読み版</h2>\n<ul>\n'
               + '\n'.join(f'<li><a href="{b}">{b}</a></li>' for b in whole)
               + '\n</ul>\n' if whole else '')
            + '<p><a href="../README.html">最初のページへ戻る</a>　'
              '<a href="../traceability.html">トレーサビリティ索引へ</a></p>')
    open(os.path.join(pkg, '14_tlf', 'index.html'), 'w', encoding='utf-8',
         newline='\n').write(page('図表の一覧', body))


def add_acrf_nav(dest):
    """aCRF の各帳票に、索引と入口へ戻るリンクを足す。

    索引からは帳票の項目（`#fieldNN`）へ直接飛ぶので、戻る道が無いと行き止まりになる。
    Ptosh が生成した HTML には戻りリンクが無いため、写した側で足す。
    """
    n = 0
    nav = ('<p style="font-family:sans-serif;font-size:13px;margin:18px 0">'
           '<a href="index.html">CRF の目次へ戻る</a>　'
           '<a href="../traceability.html">トレーサビリティ索引へ戻る</a>　'
           '<a href="../README.html">最初のページへ戻る</a></p>\n')
    for p in sorted(glob.glob(os.path.join(dest, '*.html'))):
        if os.path.basename(p) == 'index.html':
            continue
        t = open(p, encoding='utf-8', errors='replace').read()
        if 'CRF の目次へ戻る' in t:
            continue
        t = (t.replace('</body>', nav + '</body>', 1) if '</body>' in t else t + nav)
        open(p, 'w', encoding='utf-8', newline='\n').write(t)
        n += 1
    return n


def write_environment(pkg):
    """作成に使った R の実行時情報。renv.lock が持たない OS・ロケール・文字コードを残す。

    版の一覧は renv.lock が正本なので写さない。Rscript が呼べない端末では sessionInfo() を
    取れないので、その旨を書いて残す（無いことが分かる形にする）。
    """
    ver = json.load(open(os.path.join(REPO, 'renv.lock'), encoding='utf-8'))['R']['Version']
    head = ('作成に使った R の実行時情報\n'
            f'  R の版           {ver}（reproduce/renv.lock の R.Version）\n'
            '  パッケージの版   reproduce/renv.lock が持つ（ここには写さない）\n'
            f'  記録した日時     {datetime.datetime.now().astimezone().isoformat(timespec="seconds")}\n\n')
    si = ''
    for exe in ('Rscript', os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs',
                                        'R', 'R-' + ver, 'bin', 'Rscript.exe')):
        try:
            r = subprocess.run([exe, '-e', 'sessionInfo()'], capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=180)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and r.stdout.strip():
            si = 'sessionInfo()\n' + r.stdout.strip() + '\n'
            break
    if not si:
        si = ('sessionInfo() は取れなかった（この端末で Rscript を起動できない）。'
              'OS・ロケール・文字コードは記録できていない。\n')
    open(os.path.join(pkg, 'reproduce', 'environment.txt'), 'w', encoding='utf-8',
         newline='\n').write(head + si)
    return ver


# --- 再現の手順 -------------------------------------------------------------------------
# 索引を作り直す Python 一式。索引はブラウザで開く1枚の HTML で、中の解析値は組み立て時の
# ARD から埋め込む。図表を作り直したら索引も同じ状態にできるよう、生成のコードと画面の
# テンプレートを同梱する（2026-08-30。C2-080）。R は要らず標準ライブラリだけで動く。
TRACE_SCRIPTS = ('build-traceability.py', 'traceability_template.html', 'boxpath.py',
                 'rebuild-traceability.py',
                 # ARS の ReportingEvent を作り直す一式。生成物だけを渡すと、受け取った側は
                 # 中身を確かめられても直して作り直すことができない。ARD まで手元で再現できる
                 # 相手が、その ARD から組み立てた ReportingEvent だけは検算できないという
                 # 中途半端さを残さない（2026-08-30。C2-145）
                 'build-ars-json.py', 'rebuild-ars.py',
                 'check-ars-json.py', 'compare-ars-json.py')

# SDTM の define.xml を作り直す一式（2026-09-05。段F）。同梱するのは、define が
# 規制へ出すメタデータでありながら、この一式の中では作り直せないものとして残っていたため。
# 生成は受領 define.xml と docs/metadata/ の宣言だけを読むので、実装系統に依らない。
# check-sdtm-declarations.py は宣言と実データの照合で、生成と対になる。これが無いと
# 宣言が実データを言い直したまま確かめられない。
# ADaM 側は入れない。build-adam-define.py は生成の本体をスキル cdisc-define-xml に置いた
# 包みで、本体はこのリポジトリにも納品パッケージにも無い。CSV だけ渡しても作り直せない。
DEFINE_SCRIPTS = ('update-define-xml.py', 'check-sdtm-declarations.py')

# 再現の手順に段として並べる R。前の段の出力を次の段が読むので順を入れ替えられない。
# 役割と出力先だけを持ち、中身の説明は書かない（.R の頭書きには古い件数が残っており、
# そのまま写すと納品物へ古い数字が入る）。作り直したものの規模は下で実物を数えて出す。
STAGES = [('CSVtoSDTM', '受領CSVと外部データから SDTM を作る', 'datasets/r/sdtm/'),
          ('SDTMtoADaM', 'SDTM から解析用データセット（ADaM）を作る', 'datasets/r/adam/'),
          ('ARD', 'ADaM から結果値（ARD）を作る', 'datasets/r/ard/'),
          ('TLF', 'ARD から図表を描く', 'output/tlf/ と output/compare/')]



RUN_R_TEMPLATE = """## 再現の入口。renv を明示して活性化するので、.Rprofile が配る経路で落ちても
## renv.lock と同じ版のパッケージで走る。
## 使い方は次の2つ。
##   Rscript run.R          全段を順に走らせる
##   Rscript run.R ARD      指定した段だけ走らせる（前の段の出力が要る）
if (file.exists("renv/activate.R")) source("renv/activate.R")

STAGES <- c(%(stages)s)
TRIAL  <- "%(trial)s"

.a  <- commandArgs(trailingOnly = TRUE)
todo <- if (length(.a)) .a else STAGES
bad  <- setdiff(todo, STAGES)
if (length(bad)) {
  stop("知らない段: ", paste(bad, collapse = ", "),
       "。使えるのは ", paste(STAGES, collapse = " "), " です")
}
rscript <- file.path(R.home("bin"), "Rscript")
for (s in todo) {
  f <- file.path("program", "r", paste0(TRIAL, "_", s, ".R"))
  if (!file.exists(f)) stop("プログラムが無い: ", f)
  message("==== ", s)
  st <- system2(rscript, shQuote(f))
  if (st != 0) stop(s, " が終了コード ", st, " で終わった")
}
message("すべての段が終わった")
"""


def write_run_r(pkg, tid):
    """reproduce/run.R を書き出す。

    配る経路で先頭がドットのファイルが落ちることがある（Box Drive の同期で
    reproduce/.Rprofile が消えていた。2026-09-06 の独立レビューの所見1）。
    .Rprofile が無いと renv が活性化されず、lock と違う版のパッケージで走る。
    ドットに依らない入口を別に置き、手順書はこちらを案内する。.Rprofile も
    従来どおり同梱する（R を対話で開く使い方はそちらが受ける）。
    段の並びは STAGES が正本で、この入口と手順書の両方が同じ並びを読む。
    """
    body = RUN_R_TEMPLATE % {
        'stages': ', '.join('"' + s[0] + '"' for s in STAGES),
        'trial': tid,
    }
    with open(os.path.join(pkg, 'reproduce', 'run.R'), 'w',
              encoding='utf-8', newline=chr(10)) as fh:
        fh.write(body)

# 作り直したものを納品したものと突き合わせる手順。左から、突き合わせる対象、使う突合
# プログラム、同梱してある納品時のもの、作り直したもの、読むときの断り。パスは
# reproduce/ を起点にする。
CHECKS = [('結果値（ARD）', 'Compare', '../data/ard/ard_cards_r.csv',
           'datasets/r/ard/ard_cards_r.csv',
           'この突合は最後に主要評価項目の判定も見ます。判定は SAS 系と R 系の両方が'
           '書き出したものを比べる作りで、SAS 系はこの一式に入れていないので'
           '「判定の書き出しが揃っていない（SAS: FALSE / R: TRUE）」と出て'
           '「不一致がある」で終わります。値そのものが一致したかは、その上にある'
           '「整数の突合」「実数の突合」「文字の突合」の不一致 0 行を見てください'),
          ('図表のセル（日本語）', 'CompareTLF', 'expected/tlf_cells_r_ja.csv',
           'output/compare/tlf_cells_r_ja.csv', ''),
          ('図表のセル（英語）', 'CompareTLF', 'expected/tlf_cells_r_en.csv',
           'output/compare/tlf_cells_r_en.csv', ''),
          ('ADaM', 'CompareADaM', '../data/adam', 'datasets/r/adam/json', ''),
          ('SDTM', 'CompareSDTM', '../data/sdtm', 'datasets/r/sdtm/json',
           'この突合は SDTM の20ドメインに加えて、SDTM の外に置いた PV.AE_CO も見ます。'
           'その突合相手はこの一式に入れていないので「ファイルが無い」と出て異常終了します。'
           'ドメインごとの「不一致のある変数 0 個」を見てください')]


def copy_trace_scripts(pkg):
    """索引を作り直す Python 一式を reproduce/scripts/ へ写す"""
    d = os.path.join(pkg, 'reproduce', 'scripts')
    for n in TRACE_SCRIPTS + DEFINE_SCRIPTS:
        copy(os.path.join(SCRIPTS, n), os.path.join(d, n))
    return len(TRACE_SCRIPTS)


def copy_expected(pkg, box):
    """突合に使う納品時のセル台帳を reproduce/expected/ へ写す。

    作り直した図表が納品したものと同じかは、図表のセル台帳どうしを突き合わせて判定する。
    台帳は図表そのものから作られるので、期待する値を手順書へ書かずに済む。
    """
    n = 0
    for lang in ('ja', 'en'):
        src = os.path.join(box, 'output', 'compare', 'tlf_cells_r_' + lang + '.csv')
        if os.path.exists(src):
            copy(src, os.path.join(pkg, 'reproduce', 'expected', os.path.basename(src)))
            n += 1
    return n


def n_files(*parts):
    return len(glob.glob(os.path.join(*parts)))


def write_reproduce_guide(pkg, box, rver, n_trace, n_exp):
    """再現の手順。入力・実行の順・期待される出力・成功の判定・つまずいたときを1枚にする。

    件数と名前はパッケージの中身を数えて出し、各段が何をするかは同梱した .R の頭書きから
    読む。手順書へ写した値はいずれズレるので持たない（2026-08-30。C2-076・C2-078・C2-079）。
    """
    tid = boxpath.trial_id()
    rep = os.path.join(pkg, 'reproduce')

    def names(*parts):
        return '、'.join('<code>' + os.path.basename(x) + '</code>'
                         for x in sorted(glob.glob(os.path.join(*parts))))

    b = ['<h1>再現の手順</h1>',
         '<div class="note">この手順は、解析を実際に走らせ直す担当者（R を扱う統計解析の'
         '実務者）向けです。図表・索引・CRF を読むだけであれば、何も導入する必要はありません。'
         '<a href="../README.html">最初のページ</a>から開いてください。</div>',
         '<h2>用意するもの</h2>',
         '<ul>',
         '<li>R … 作成に使ったのは ' + rver + ' です。パッケージの版は '
         '<code>renv.lock</code> が固定します</li>',
         '<li>図を描く土台（cairo） … 図4件（生存曲線）は SVG を cairo 経由で書き出します。Windows の CRAN 版 R は同梱していますが、macOS の CRAN 版 R は XQuartz を入れないと読めません。無いまま走らせると図の段が「コネクションを開くことができません」で異常終了します。<code>capabilities("cairo")</code> が <code>TRUE</code> を返すことを先に確かめてください</li>',
         '<li>この一式をフォルダごと置いた場所。<code>reproduce/</code> を起点に R を開きます。'
         'ファイルを1つだけ取り出すと入力の場所を見つけられません</li>',
         '<li>網 … <code>renv::restore()</code> が R のパッケージ配布網（CRAN）から'
         'パッケージを取りに行きます。組織のプロキシを通す設定が要ることがあります</li>',
         '<li>Python … トレーサビリティ索引・ReportingEvent・データセットの定義'
         '（define.xml）を作り直すときに要ります。図表を作り直すだけなら要りません。'
         '同梱した9本のうち <code>check-ars-json.py</code> だけが <code>jsonschema</code> を'
         '要り（<code>python -m pip install jsonschema</code>）、ほかは標準ライブラリだけで'
         '動きます</li>',
         '</ul>',
         '<h3>網につながらないとき</h3>',
         '<p><code>renv::restore()</code> はパッケージを取りに行くので、網から切り離された'
         '端末では走りません。<code>renv</code> 自身も初回に取りに行きます'
         '（<code>renv/activate.R</code> が行います）。次のいずれかで進めます。</p>',
         '<ul>',
         '<li>網につながる端末で <code>reproduce/</code> を開いて <code>renv::restore()</code> を'
         '走らせ、できた <code>renv/library/</code> ごと持ち込む。同じ OS と同じ R の版であれば'
         'そのまま使えます</li>',
         '<li><code>renv.lock</code> が挙げる版の書庫を持ち込み、'
         '<code>install.packages("&lt;書庫のファイル&gt;", repos = NULL, type = "source")</code> で'
         '入れる</li>',
         '<li>下の窓口へ連絡する。パッケージの写しを渡せます</li>',
         '</ul>',
         '<h2>入力</h2>',
         '<p>' + data_snapshot(box) + '</p>',
         '<ul>',
         '<li><code>input/rawdata/</code> … 受領CSV '
         + str(n_files(rep, 'input', 'rawdata', '*.csv')) + ' 件（'
         + names(rep, 'input', 'rawdata', '*.csv') + '）</li>',
         '<li><code>input/ext/</code> … 外部データ '
         + str(n_files(rep, 'input', 'ext', '*.csv')) + ' 件（'
         + names(rep, 'input', 'ext', '*.csv') + '）</li>',
         '<li><code>input/rawdata/</code> の下の受領 define.xml … データセンターから'
         '受領したデータセットの定義。受領時の階層のまま置いてあります。SDTM の '
         'define.xml を作り直すときの材料です</li>',
         '</ul>',
         '<p>宣言と仕様（図表の宣言・表示文言・変数の対応・試験の設計）は '
         '<code>docs/metadata/</code> と <code>docs/validation/acceptance/</code> に'
         'あります。リポジトリと同じ位置に置いてあるので、同梱のプログラムは自分の位置から'
         '同じ相対パスで辿れます。</p>',
         '<p>置き場所は変えないでください。R は起点の下を上へ辿り、'
         '<code>input/rawdata/DM.csv</code> を目印にデータの根を決めます。</p>',
         '<h2>実行の順</h2>',
         '<p><code>reproduce/</code> を起点に R を開き、最初に一度だけ '
         '<code>renv::restore()</code> を走らせます。その後、次の順に走らせます。前の段の'
         '出力を次の段が読むので、順を入れ替えられません。</p>',
         '<p>段を1つずつ叩く代わりに <code>Rscript run.R</code> でまとめて走らせられます。この入口は <code>renv/activate.R</code> を自分で読むので、配る経路で <code>.Rprofile</code>（先頭がドットのファイル）が落ちていても <code>renv.lock</code> と同じ版で走ります。段を1つだけ走らせるときは <code>Rscript run.R ARD</code> のように段の名前を渡します。</p>',
         '<ol>']
    for tag, role, dest in STAGES:
        b.append('<li><code>Rscript program/r/' + tid + '_' + tag + '.R</code> … ' + role
                 + '　出力 <code>' + dest + '</code></li>')
    b.append('</ol>')
    b.append('<p>この一式が持つ成果物の規模は次のとおりです。作り直したものがこれと違えば、'
             '入力か環境のどこかが違っています。</p>')
    ard = os.path.join(pkg, 'data', 'ard', 'ard_cards_r.csv')
    n_ard = (sum(1 for _ in open(ard, encoding='utf-8-sig')) - 1
             if os.path.exists(ard) else 0)
    b += ['<ul>',
          '<li>SDTM … ' + str(n_files(pkg, 'data', 'sdtm', '*.json')) + ' ドメイン</li>',
          '<li>ADaM … ' + str(n_files(pkg, 'data', 'adam', '*.json')) + ' データセット</li>',
          '<li>結果値（ARD）… ' + format(n_ard, ',') + ' 行</li>',
          '<li>図表 … 言語ごとに ' + str(n_files(pkg, '14_tlf', 'ja', '*.html'))
          + ' 件（日本語と英語）</li>',
          '</ul>',
          '<h2>作り直したものが納品したものと同じかを確かめる</h2>',
          '<p>各段が異常終了しないことが最初の条件です。そのうえで、同梱した突合プログラムで'
          '納品時のものと突き合わせます。突合プログラムは不一致を見つけると異常終了し、'
          '不一致の中身を <code>output/compare/</code> に書きます。すべて一致すれば、'
          '作り直した結果は納品したものと同じです。</p>',
          '<ol>']
    for what, prog, ref, made, note in CHECKS:
        b.append('<li>' + what + ' … <code>Rscript program/r/' + tid + '_' + prog
                 + '.R --a=' + ref + ' --b=' + made + '</code>'
                 + ('　' + note if note else '') + '</li>')
    b += ['</ol>',
          '<p>ファイルそのものの同一性は <code>../manifest.csv</code> の SHA-256 で見ます。'
          'ただし作成日を名前に持つファイル（通し読みの HTML と Excel）は作り直した日で名前が'
          '変わり、生成日時を書き込むファイルは中身も変わります。値が同じかどうかは上の突合で'
          '見てください。</p>',
          '<h2>トレーサビリティ索引を作り直す</h2>',
          '<p>索引は図表とは別に作ります。図表を作り直したら、次を走らせると索引が持つ'
          '解析値と系譜も同じ状態になります。R は要りません。</p>',
          '<ul><li><code>python scripts/rebuild-traceability.py</code></li></ul>',
          '<p>索引を作るのは <code>scripts/build-traceability.py</code> で、画面は '
          '<code>scripts/traceability_template.html</code> が持ちます。'
          '<code>rebuild-traceability.py</code> は、この一式の並びを索引生成が読む並びへ'
          '渡すだけの包みです（同梱 ' + str(n_trace) + ' ファイル）。</p>',
          '<h2>ReportingEvent（ARS）を作り直す</h2>',
          '<p>解析の定義と結果値を CDISC の標準形式で1つにまとめたものが '
          '<code>16_1_9_methods/reporting-event-r.json</code> です。図表を作り直したら、'
          '次を走らせると同じ状態になります。R は要りません。</p>',
          '<ul><li><code>python scripts/rebuild-ars.py</code></li></ul>',
          '<p>作り直したものが納品したものと同じかは、次で確かめます。'
          '納品時のものは <code>../16_1_9_methods/reporting-event-r.json</code> です。</p>',
          '<ul><li><code>python scripts/compare-ars-json.py '
          '--a ../16_1_9_methods/reporting-event-r.json --b &lt;作り直したもの&gt;</code></li></ul>',
          '<p>標準（ARS v1.0）への適合そのものは次が見ます。</p>',
          '<ul><li><code>python scripts/check-ars-json.py '
          '--json ../16_1_9_methods/reporting-event-r.json</code></li></ul>',
          '<p>組み立てるのは <code>scripts/build-ars-json.py</code> で、'
          '<code>rebuild-ars.py</code> は、結果値の置き場だけを生成が読む形へ渡す包みです。</p>',
          '<h2>データセットの定義（define.xml）を作り直す</h2>',
          '<p><code>data/sdtm/define.xml</code> は、データセンターから受領した define.xml に'
          'この解析で足した変数とドメインを反映したものです。受領した define.xml は '
          '<code>input/rawdata/</code> の下に受領時のまま同梱してあるので、次で作り直せます。'
          'R は要りません。</p>',
          '<ul><li><code>python scripts/update-define-xml.py '
          '--out-dir &lt;作り直したものの置き場&gt; '
          '--compare ../data/sdtm/define.xml</code></li></ul>',
          '<p><code>--compare</code> を付けると、作り直したものが同梱の define.xml と'
          '同じかをその場で見ます。作成日時（<code>CreationDateTime</code>）は回ごとに'
          '変わるので、そこだけ伏せて1バイトずつ比べます。生成が読むのは受領 define.xml と '
          '<code>docs/metadata/</code> の宣言だけで、データセットは読みません。宣言が SDTM の'
          '実データと合っているかは次が見ます。</p>',
          '<ul><li><code>python scripts/check-sdtm-declarations.py '
          '--json-dir ../data/sdtm</code></li></ul>',
          '<p>ADaM の <code>data/adam/define.xml</code> を作り直す道はこの一式に入れて'
          'いません。生成の本体が解析側の別の道具にあり、ここへ移すと同じ生成が2つに'
          'なるためです。中身は '
          '<a href="../16_1_9_methods/define_adam.html">ADaM の define</a> で読めます。</p>',
          '<p><code>define.xml</code> をブラウザで直接開いても、手元のファイル'
          '（<code>file://</code>）では表示用のスタイルシートが当たらないことがあります'
          '（多くのブラウザが既定で止めます）。素の XML が出たときは '
          '<a href="../16_1_9_methods/define_sdtm.html">SDTM の define</a> と '
          '<a href="../16_1_9_methods/define_adam.html">ADaM の define</a> を'
          '見てください。読み物としての経路はこの2つです。</p>',
          '<h2>うまくいかないとき</h2>',
          '<ul>',
          '<li>「trial.json が見つかりません」「仕様ファイルが見つかりません」… 起点が '
          '<code>reproduce/</code> になっていません。フォルダごと置いたうえで、そこを作業'
          'ディレクトリにして R を開いてください</li>',
          '<li>「input/rawdata/DM.csv がありません」… 一式の一部だけを取り出しています。'
          'フォルダごと置き直してください</li>',
          '<li><code>renv::restore()</code> が取りに行けない … 上の「網につながらないとき」を'
          '見てください</li>',
          '<li>Excel が出ない … Excel の出力だけが追加のパッケージを要ります。無い環境では'
          'Excel を飛ばし、HTML とセル台帳は最後まで出ます。突合はセル台帳で行うので、'
          'Excel が無くても確かめられます</li>',
          '<li>日本語が化ける … R の文字コードを UTF-8 にしてください。同梱の CSV は '
          'UTF-8 で、表計算で開くための印（BOM）が付いています</li>',
          '<li>書き込みに失敗する … 出力先が読み取り専用か、共有ストレージの同期中です。'
          '同期の対象でない場所へ置いてから走らせてください</li>',
          '<li>それでも進まない … <a href="../README.html#contact">窓口</a>へ連絡してください。'
          '走らせた段と、画面に出た最後の数行を添えてください</li>',
          '</ul>',
          '<h2>この手順に出てくるもの</h2>',
          '<ul>',
          '<li><code>expected/</code> … 納品時の図表のセル台帳 ' + str(n_exp) + ' 件。'
          '作り直した図表との突合に使います</li>',
          '<li><code>docs/</code> … R のコメントが指す仕様（md）と、プログラムが読む宣言・'
          '受入基準・試験の設定（<code>metadata/</code>・<code>validation/acceptance/</code>）。'
          'いずれも解析側のリポジトリと同じ位置に置いてあります</li>',
          '<li><code>environment.txt</code> … 作成に使った R の実行時情報（OS・ロケール・'
          '文字コード）</li>',
          '<li><a href="../16_1_9_methods/double-coding-report.html">二重作成の突合</a> … '
          'SAS 系と R 系で別々に作って突き合わせた結果と合否</li>',
          '</ul>',
          '<p><a href="../README.html">最初のページへ戻る</a></p>']
    open(os.path.join(rep, 'README.html'), 'w', encoding='utf-8', newline=NL).write(
        page('再現の手順', NL.join(b)))


def esc(s):
    """HTML の本文へそのまま出す文字列を逃がす"""
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


# --- 二重作成の突合 ---------------------------------------------------------------------
# 同じ仕様から SAS 系と R 系を別々に組み、層ごとに突き合わせている。納品するのは R 系だけで、
# SAS のプログラムと実行ログは入れない（研究責任医師の環境に SAS が無く、渡しても動かせない。
# 2026-08-30 の判断。docs/validation/records/codex-review-2-ledger.md の C2-073・C2-079・C2-110）。
# 二重に作った事実は、突合の結果と合否で示す。値はここに書かず、突合プログラムが書き出した
# 結果のファイルから読む。
LOCAL_PATH = [re.compile(r"[A-Za-z]:[\\/]Users[\\/][^\s'\"<>|]+"),
              re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/[^\s'\"<>|]+")]


def mask_local(text):
    """突合の記録に入っている端末のローカルパスを落とす。

    突合プログラムは読んだ場所を絶対パスで書く。そのまま配ると、誰のどの置き場かが外へ出る
    （check-pi-package.py の SECRET が同じものを見ており、残っていれば組み立ての最後に出る）。
    """
    for pat in LOCAL_PATH:
        text = pat.sub('<省いた場所>', text)
    return text


def compare_tlf_pairs(src):
    """図表の突合のうち、いま生きているものと、以前の命名で残っているものに分ける。

    `CompareTLF.R` は `tlf_compare_<a>_vs_<b>.csv` を出す。a・b は突き合わせたセル台帳
    `tlf_cells_<a>.csv` の名前で、台帳の名前は途中で変わっている。両側の台帳が今も置き場に
    あるものだけが現行の突合にあたるので、片側しか無いものは入れない（以前の命名で残った
    結果を、今の版の合否として見せないため）。
    """
    live, old = [], []
    for p in sorted(glob.glob(os.path.join(src, 'tlf_compare_*.csv'))):
        m = re.fullmatch(r'tlf_compare_(.+)_vs_(.+)\.csv', os.path.basename(p))
        if not m:
            continue
        sides = [os.path.join(src, 'tlf_cells_' + s + '.csv') for s in m.groups()]
        (live if all(os.path.exists(s) for s in sides) else old).append(p)
    return live, old


def write_double_coding(dest, box):
    """二重作成の突合の結果と合否を1枚にし、根拠のファイルを同梱する。

    突合の判定は突合プログラムが記録に書いた文言をそのまま出し、図表の突合は「一致しない
    セルの一覧」の行数をそのまま数える。このページは並べ直すだけで、値を持たない。
    """
    src = os.path.join(box, 'output', 'compare')
    n = 0
    b = ['<h1>二重作成の突合</h1>',
         '<p>この試験の解析は、同じ仕様から SAS 系と R 系を別々に組み、層ごとに突き合わせて'
         'います。同じ結果が別々の実装から出ることを確かめるためです。納品するのは R 系の'
         '成果物で、SAS のプログラムと実行ログは入れていません。研究責任医師の環境に SAS が'
         '無く、渡しても動かせないためです。二重に作った事実は、このページに置く突合の結果と'
         'その合否で示します。</p>',
         '<p>判定の文言は、突合プログラムがその場で書いた記録そのままです。'
         '根拠のファイルは同じフォルダに入れてあり、リンクから開けます。</p>',
         '<h2>層ごとの突合</h2>',
         '<p>データの層ごとに、SAS 系と R 系の出力を突き合わせています。実数は相対許容差、'
         '整数と文字は完全一致で見ます（許容差は記録の頭に書いてあります）。</p>',
         '<ul>']
    for pre, lay in (('sdtm', 'SDTM'), ('adam', 'ADaM'),
                     ('ard', 'ARD（図表の元になる結果値）')):
        hits = sorted(glob.glob(os.path.join(src, pre + '_compare_*.txt')))
        if not hits:
            b.append('<li>' + lay + ' … 突合の記録が置き場に無い</li>')
            continue
        name = os.path.basename(hits[-1])
        body = mask_local(open(hits[-1], encoding='utf-8', errors='replace').read())
        open(os.path.join(dest, name), 'w', encoding='utf-8', newline=NL).write(body)
        n += 1
        lines = [x.strip() for x in body.splitlines() if x.strip()]
        when = next((x for x in lines if x.startswith('実行日時')), '')
        b.append('<li>' + lay + ' … <a href="' + name + '">' + name + '</a>　'
                 + esc(when) + '　判定 ' + esc(lines[-1] if lines else '記録が空') + '</li>')
    b.append('</ul>')

    live, old = compare_tlf_pairs(src)
    b.append('<h2>図表の突合</h2>')
    b.append('<p>同じ図表を両系統で描き、セル単位で突き合わせた結果です。一覧に出るのは値が'
             '一致しなかったセルなので、0 件が一致を意味します。名前の <code>sas</code> は'
             'SAS 系の図表、<code>r</code> は R 系の図表、<code>rsas</code> は R で描きながら'
             '数値だけ SAS 系の ARD を使ったものです（描き方の違いと数値の違いを分けて見る'
             'ためです）。</p>')
    b.append('<ul>')
    for p in live:
        name = os.path.basename(p)
        with open(p, encoding='utf-8-sig', newline='') as f:
            ndiff = max(sum(1 for _ in f) - 1, 0)
        copy(p, os.path.join(dest, name))
        n += 1
        b.append('<li><a href="' + name + '">' + name + '</a>　不一致 '
                 + format(ndiff, ',') + ' セル</li>')
    b.append('</ul>')

    b.append('<h2>主要評価項目の判定</h2>')
    b.append('<p>主要評価項目は、推定値・信頼区間の下限・閾値・判定の4点を両系統がそれぞれ'
             '書き出し、上の ARD の突合で照合しています。両系統が書いた記録は次のとおりです。</p>')
    b.append('<ul>')
    for p in sorted(glob.glob(os.path.join(src, 'primary_decision_*.csv'))):
        copy(p, os.path.join(dest, os.path.basename(p)))
        n += 1
        b.append('<li><a href="' + os.path.basename(p) + '">'
                 + os.path.basename(p) + '</a></li>')
    b.append('</ul>')

    b.append('<h2>突合をやり直すには</h2>')
    b.append('<p>突合のプログラム（R で4本）は <code>reproduce/</code> に入れてあります。'
             '解析を走らせ直すと、作り直した R 系の出力を、この一式が持つ SDTM・ADaM・ARD と'
             '突き合わせられます。手順と判定のしかたは'
             '<a href="../reproduce/README.html">再現の手順</a>にあります。</p>')
    b.append('<p>突合の仕様は<a href="ard-double-coding-spec.html">二重作成の突合の仕様</a>と'
             '<a href="ard-double-coding-spec.html">二重作成の仕様</a>が持ちます。</p>')
    b.append('<p><a href="validation-report.html">検証の記録へ</a>　'
             '<a href="../README.html">最初のページへ戻る</a></p>')
    open(os.path.join(dest, 'double-coding-report.html'), 'w', encoding='utf-8',
         newline=NL).write(page('二重作成の突合', NL.join(b)))
    if old:
        print('  二重作成の突合: 以前の命名で残っている結果 '
              + '、'.join(os.path.basename(p) for p in old) + ' は入れない')
    return n + 1


def write_validation_report(pkg, trace_log, link_log, qc_json):
    """検証の記録。索引の整合・リンクの検査・適合性検査の指摘の仕分けを1枚にする。

    どれも生成時のログか docs/metadata の CSV が正本で、ここは同じ内容を PI が読める形へ
    並べ直すだけにする（値をこのスクリプトに書かない）。
    """
    qc = json.load(open(qc_json, encoding='utf-8')) if os.path.exists(qc_json) else {}

    b = ['<h1>検証の記録</h1>',
         '<p>この一式を組み立てたときに機械で確かめた結果です。組み立てのたびに作り直します。</p>']
    if qc:
        c = qc.get('counts', {})
        b.append('<h2>トレーサビリティ索引のつながり</h2>')
        b.append('<p>索引が扱う件数。' + '、'.join(f'{k} {v}' for k, v in c.items()) + '。</p>')
        b.append('<p>解析と ADaM のつながりは、ARD の由来列が ADaM を直に指すものが確定で、'
                 '変数名の一致で結ぶものは暫定です。暫定の分は、変数名が同じでも別の値を'
                 '数えている可能性が残ります。</p>')
        b.append('<h2>つながっていない箇所</h2>')
        b.append('<p>索引は正本（宣言・仕様・データ）の食い違いをそのまま映します。'
                 '次の箇所は鎖が切れており、図表から CRF まで辿れません。</p>')
        for k, v in qc.get('qc', {}).items():
            if not v:
                continue
            b.append(f'<p>{esc(qc.get("notes", {}).get(k, k))}：{len(v)} 件</p>')
            b.append('<p class="n">' + esc('、'.join(v[:60]))
                     + (f'　ほか {len(v) - 60} 件' if len(v) > 60 else '') + '</p>')
    b.append('<h2>リンクの検査</h2>')
    b.append('<p>この一式のリンクが相対パスだけで閉じているか（外部へ出ない・切れない・'
             '飛び先の見出しが実在する）を機械で確かめた結果です。'
             '誤りが1件でもあれば組み立て自体が失敗するため、配ったものは常に 0 件です。</p>')
    b.append('<pre class="n">' + esc(link_log.strip()) + '</pre>')
    b.append('<p class="n">この検査は本体に対する結果です。この記録と '
             '<code>manifest.csv</code> は検査の後に作られるので、'
             '組み立ての最後にもう一度同じ検査を通しています。</p>')
    dis = meta_rows('core-issue-disposition.csv')
    if dis:
        cnt = {}
        for r in dis:
            cnt[r['disposition']] = cnt.get(r['disposition'], 0) + 1
        b.append('<h2>電子データの適合性検査</h2>')
        b.append('<p>SDTM のデータセットを CDISC CORE（CDISC が配布する適合性検査の実装）に'
                 'かけた結果の仕分けです。指摘の規則ごとに、直したもの・データの作りに由来し'
                 '直せないもの（既知）を分けています。件数は '
                 + '、'.join(f'{k} {v} 規則' for k, v in sorted(cnt.items())) + '。</p>')
        b.append('<ul>')
        for r in dis:
            b.append(f'<li><code>{esc(r["core_id"])}</code> {esc(r["disposition"])}'
                     f'　{esc(r["note"])}</li>')
        b.append('</ul>')
        b.append('<p>指摘ごとの根拠と対処は'
                 '<a href="../reproduce/docs/validation/records/sdtm-conformance-findings-20260815.md">'
                 '適合性検証の結果と仕分け</a>にあります。'
                 '検査に使った版と規則集は同記録が持ちます。</p>')
    b.append('<h2>二重作成の突合</h2>')
    b.append('<p>同じ仕様から SAS 系と R 系を別々に組み、層ごとに突き合わせています。'
             '突合の結果と合否は<a href="double-coding-report.html">二重作成の突合</a>に'
             'まとめてあります。</p>')
    b.append('<h2>索引を組み立てたときのログ</h2>')
    b.append('<pre class="n">' + esc(trace_log.strip()) + '</pre>')
    b.append('<p><a href="../README.html">最初のページへ戻る</a></p>')
    open(os.path.join(pkg, '16_1_9_methods', 'validation-report.html'), 'w',
         encoding='utf-8', newline='\n').write(page('検証の記録', '\n'.join(b)))


MANIFEST = ('manifest.csv', 'manifest.html')


def write_manifest(pkg):
    """同梱物の一覧。相対パス・バイト数・SHA-256 を機械可読（CSV）と読み物（HTML）で出す。

    配った先で欠けや取り違えが起きていないか、作り直した結果が納品したものと同じかを、
    受け取った側だけで確かめられるようにする。一覧そのもの2件は自分を数えられないので外す。
    """
    rows = []
    for r, _, fs in os.walk(pkg):
        for f in sorted(fs):
            p = os.path.join(r, f)
            rel = os.path.relpath(p, pkg).replace(os.sep, '/')
            if rel in MANIFEST:
                continue
            h = hashlib.sha256()
            with open(p, 'rb') as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b''):
                    h.update(chunk)
            rows.append((rel, os.path.getsize(p), h.hexdigest()))
    rows.sort()
    gen = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    with open(os.path.join(pkg, 'manifest.csv'), 'w', encoding='utf-8-sig',
              newline='') as f:
        w = csv.writer(f)
        w.writerow(['path', 'bytes', 'sha256'])
        w.writerows(rows)
    tot = sum(n for _, n, _ in rows)
    b = [f'<h1>同梱物の一覧</h1>',
         f'<p>版 <code>{os.path.basename(pkg)}</code>（フォルダ名が版の識別子です）。'
         f'生成 {gen}。{len(rows)} ファイル・{tot / 1e6:.1f} MB。</p>',
         '<p>SHA-256 はファイルの中身から計算した値です。中身が1バイトでも違えば値が'
         '変わるので、受け取ったものが送ったものと同じかを、この値の照合で確かめられます。'
         '機械で読む形は <code>manifest.csv</code> です。'
         'この一覧自身の2ファイルは対象に含みません。</p>',
         '<ul class="n">']
    b += [f'<li><code>{p}</code>　{n:,} バイト　<code>{h}</code></li>' for p, n, h in rows]
    b += ['</ul>', '<p><a href="README.html">最初のページへ戻る</a></p>']
    open(os.path.join(pkg, 'manifest.html'), 'w', encoding='utf-8',
         newline='\n').write(page('同梱物の一覧', '\n'.join(b)))
    return len(rows), tot


def add_index_fallback(path):
    """トレーサビリティ索引に、JavaScript が動かないときの案内と検証の記録への入口を足す。

    索引は単一の HTML で、画面は JavaScript が組み立てる。共有ストレージのプレビューや
    JavaScript を止めた環境では白紙になるため、静的な入口（図表の一覧・CRF の目次）を
    本文へ置く。索引の到達率と未接続の一覧も、画面からは見えないので入口を出す。
    """
    t = open(path, encoding='utf-8').read()
    if '<main>' not in t or '<footer>' not in t:
        sys.exit('索引の作りが変わっている。add_index_fallback の差し込み位置を直す。')
    t = t.replace('<main>', '<main>\n<noscript>\n'
                  '<div style="background:#fffbe6;border-left:4px solid #f0c000;'
                  'padding:9px 13px;margin:12px 0;font-size:.9rem">'
                  'この索引は JavaScript で動きます。画面が出ないときは、フォルダ全体を'
                  'ダウンロードしてから開くか、次の静的な入口を使ってください。'
                  '<a href="14_tlf/index.html">図表の一覧</a>　'
                  '<a href="16_1_2_acrf/index.html">CRF の目次</a>　'
                  '<a href="README.html">最初のページ</a></div>\n</noscript>', 1)
    t = t.replace('<footer>', '<footer>\n'
                  '  <a href="16_1_9_methods/validation-report.html">'
                  'この索引の到達率と、つながっていない箇所の一覧</a>\n'
                  '  <a href="14_tlf/index.html">図表の一覧</a>\n'
                  '  <a href="README.html">最初のページ</a>\n', 1)
    open(path, 'w', encoding='utf-8', newline='\n').write(t)


def data_snapshot(box):
    """解析に使った受領データの識別。受領物のフォルダ名が事実を持つので、そこから読む"""
    d = os.path.join(box, 'input', 'rawdata')
    arc = sorted(os.path.basename(p) for p in glob.glob(os.path.join(d, '*'))
                 if os.path.isdir(p) and re.match(r'^\d{8} ', os.path.basename(p)))
    n_csv = len(glob.glob(os.path.join(d, '*.csv')))
    if not arc:
        return ('解析に使った受領データの識別子が取れなかった'
                '（受領物の置き場にフォルダが無い）。')
    inner = sorted(os.path.basename(p) for p in
                   glob.glob(os.path.join(d, arc[-1], '*')) if os.path.isdir(p))
    return ('図表は、データセンターから受領した固定データ '
            f'<code>{arc[-1]}</code>'
            + (f'（受領物の中の抽出 <code>{inner[0]}</code>）' if inner else ' ')
            + f'から作っています。受領した CSV {n_csv} 件は '
            '<code>reproduce/input/rawdata/</code> に同梱しています。'
            f'受領物はこれまでに {len(arc)} 版あり、上に書いたものが最新です。')


def contact_block():
    """問い合わせ先。値の正本は docs/metadata/delivery-contact.csv

    値が未定のときに、項目名を並べて「…は、この一式を渡した担当者に確かめてください」と
    出す作りをやめた（2026-09-05。C3-323）。申し込みという枠組みを落として項目が
    問い合わせ先だけになったため、その言い方では「問い合わせ先は、この一式を渡した担当者に
    確かめてください」となり、文が自分を指して循環する。

    未定のときに読み手が実際にたどれる先は、この一式を渡した担当者そのものである。
    そこで項目名を出さず、その担当者が窓口であることを1文で述べる。何が同梱されて
    いないかはここで列挙しない（列挙はパッケージの中身という実装の事実の言い直しに
    あたり、古くなれば README が再び実態と矛盾する）。値が決まって CSV へ入れば、
    この節はその値を出す。
    """
    rows = meta_rows('delivery-contact.csv')
    li = [f'<li>{r["item"]} … {r["value"]}</li>' for r in rows if r['value'].strip()]
    if li:
        return '<ul>\n' + '\n'.join(li) + '\n</ul>'
    return ('<p>この一式を渡した統計解析の担当者が窓口です。同梱されていないものが要るとき、'
            '再現の途中で行き詰まったとき、記述の意味が読み取れないときは、その担当者へ'
            '連絡してください。</p>')


def primary_result(box):
    """主要評価項目の結果。値の正本は判定の記録（output/compare/primary_decision_r.csv）で、
    ここへ写すのではなく組み立てのたびに読む。README は毎回作り直すので古くならない。

    数値を入口へ出さない方針を 2026-08-30 に改めた。決め方だけを示して結論を図表の中へ
    置いておくと、受け取った側は主要評価項目の結論を知るために図表を1つずつ開くことに
    なる。結論は解析の要であり、入口に無いことによる不便が、二重に持つ危うさを上回る
    （C2-066・C2-089・C2-092）。
    """
    p = os.path.join(box, 'output', 'compare', 'primary_decision_r.csv')
    if not os.path.exists(p):
        p = os.path.join(box, 'output', 'compare', 'primary_decision_sas.csv')
    if not os.path.exists(p):
        return ('<p class="n">判定の記録が同梱されていないため、結論は図表そのものを'
                '見てください。</p>')
    with open(p, encoding='utf-8-sig', newline='') as f:
        d = list(csv.DictReader(f))[0]
    pe = {r['item']: r['value'] for r in meta_rows('primary-endpoint.csv', ACC)}
    # 主要評価項目の呼び名は試験ごとに違う。受入基準の CSV が endpoint_label を持てば
    # それを出し、無ければ一般の語で書く。疾患固有の略号を汎用層のコードへ書かない
    label = pe.get('endpoint_label') or '主要評価項目の割合'

    def pct(x):
        try:
            return f'{float(x) * 100:.1f}%'
        except (TypeError, ValueError):
            return str(x)

    judge = ('閾値を上回った' if d.get('decision') == 'MET' else '閾値を上回らなかった')
    return ('<ul>\n'
            f'<li>{d.get("timepoint", "")} 時点の{label} … <code>{pct(d.get("estimate"))}</code>'
            f'（95%信頼区間 {pct(d.get("lcl"))} から {pct(d.get("ucl"))}）</li>\n'
            f'<li>閾値 … <code>{pct(pe.get("threshold", d.get("threshold")))}</code></li>\n'
            f'<li>判定 … <code>{d.get("decision", "")}</code>　'
            f'信頼区間の下限が{judge}</li>\n'
            '</ul>\n')


def ard_rows(box):
    """ARD（結果値）を読む。納品する図表は R 系なので R 系を先に見て、無ければ SAS 系。

    パッケージの data/ard/ へ写すのと同じファイルを読む。件数を README へ写さず、
    組み立てのたびにここから引く（C2-092）。
    """
    for sysname, name in (('r', 'ard_cards_r.csv'), ('sas', 'ard_cards.csv')):
        p = os.path.join(box, 'datasets', sysname, 'ard', name)
        if os.path.exists(p):
            with open(p, encoding='utf-8-sig', newline='') as f:
                return list(csv.DictReader(f))
    return []


def km_counts(rows, analysis_id):
    """生存時間解析の要約（対象例数・イベント数・打ち切り数）を ARD から取る。

    同じ統計量名が時点ごとの行にも出る（各時点の打ち切り数）ので、水準の付かない
    要約行だけを見る。取れない統計量は入れずに返し、呼ぶ側が無い前提で組み立てる。
    """
    out = {}
    for r in rows:
        if (r['analysis_id'] == analysis_id and not r['variable_level']
                and r['stat_name'] in ('N', 'nevent', 'ncensor')):
            try:
                out[r['stat_name']] = int(float(r['stat_num']))
            except (TypeError, ValueError):
                pass
    return out


def sensitivity_id(rows, prim_id):
    """主解析と同じ出力に載る、別の変数を使う解析の ID。

    感度解析は、主解析と同じ出力に、判定の定義を取り替えた別の変数で載る。出力番号も
    変数名も試験ごとに違うので、ここへ書かず ARD の並びから引き当てる。
    """
    same = [r for r in rows if r['analysis_id'] == prim_id]
    if not same:
        return None, None
    oid, var = same[0]['output_id'], same[0]['variable']
    for r in rows:
        if r['output_id'] == oid and r['variable'] != var and r['analysis_id'] != prim_id:
            return r['analysis_id'], r['variable']
    return None, None


# 解析の前提と限界。文言の正本は docs/reporting/analysis-limitations.md の「限界の一覧」で、
# README・総括報告書の草稿・総括報告書の3つが同じ限界を述べるため、1本の md から引く
# （C3-319）。ここには文言を置かず、節の名前と、差し込む値の作り方だけを持つ。
LIMITS_MD = 'reporting/analysis-limitations.md'
LIMITS_SECTION = '限界の一覧'

_SPEC_HTML = [None]


def spec_html():
    """build-spec-html.py を読み込む。md の行内記法の変換（`inline`）と、
    16_1_9_methods へ HTML で入る仕様の一覧（`FILES`）を、そちらの1か所から借りる。

    ファイル名に `-` があり import できないので、パスから読み込む。読み込んだ時点では
    何も走らない（`main()` は `__main__` のときだけ）。
    """
    if _SPEC_HTML[0] is None:
        import importlib.util
        f = os.path.join(SCRIPTS, 'build-spec-html.py')
        spec = importlib.util.spec_from_file_location('build_spec_html', f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _SPEC_HTML[0] = mod
    return _SPEC_HTML[0]


def spec_link(text, url):
    """md の中のリンクを、パッケージの中の行き先へ直す。

    16_1_9_methods へ HTML で入る仕様だけをリンクにし、入らないものはリンクを外して
    題名だけ残す。同梱されない文書を指すと check-pi-package.py が ERROR を出すため、
    実際に作られるものの一覧（build-spec-html.py の FILES）で照合する。
    """
    head = url.split('#')[0]
    base = head.rsplit('/', 1)[-1]
    if base in {os.path.basename(f) for f in spec_html().FILES}:
        return '<a href="16_1_9_methods/%s.html%s">%s</a>' % (
            os.path.splitext(base)[0], url[len(head):], text)
    return text


def md_section_items(path, heading):
    """md の指定した見出しの下にある箇条書きを、1項目1文字列で返す。

    見出しが変わったところで終わる。字下げした続きの行は前の項目へつなぐ。
    """
    items, on = [], False
    for ln in open(path, encoding='utf-8').read().splitlines():
        if ln.startswith('#'):
            on = ln.lstrip('#').strip() == heading
        elif not on:
            continue
        elif ln.startswith('- '):
            items.append(ln[2:].strip())
        elif items and ln[:1].isspace() and ln.strip():
            items[-1] += ln.strip()
    return items


def limits_block(box):
    """解析の前提と限界。結論をどう読むかを入口に置く（C2-092）。

    文言は持たず、docs/reporting/analysis-limitations.md の「限界の一覧」を読んで組み立てる
    （C3-319）。同じ限界を README・総括報告書の草稿・総括報告書の3つが述べるので、
    正本を1本にして写しを持たない。

    件数・閾値・解析IDは md にも書かず、組み立てのたびに正本から読んで差し込む。
    イベント数と打ち切り数は ARD（`data/ard/` へ同梱するのと同じファイル）、閾値と
    判定の式は docs/validation/acceptance/primary-endpoint.csv。値が取れないときは
    その差し込みを空文字にするか、短い言い換えに替えて、誤った数を出さない。感度解析の
    ように解析そのものが無いことがあり得るものは、値が取れなければ項目ごと落とす。
    """
    pe = {r['item']: r['value'] for r in meta_rows('primary-endpoint.csv', ACC)}
    rows = ard_rows(box)
    prim_id = pe.get('analysis_id', '')
    main = km_counts(rows, prim_id)
    sid, svar = sensitivity_id(rows, prim_id)
    sens = km_counts(rows, sid) if sid else {}

    try:
        thr = f'{float(pe.get("threshold", "")) * 100:.1f}%'
    except (TypeError, ValueError):
        thr = pe.get('threshold', '')

    # 値が None のものは、その項目を落とす合図にする（空文字は「書かずに続ける」）
    vals = {
        '{閾値}': ('（' + thr + '）') if thr else '',
        '{比較の式}': pe.get('comparison', ''),
        '{主解析の内訳}': (
            '主解析（{}例）ではイベント{}例・打ち切り{}例でした。'.format(
                main['N'], main['nevent'], main['ncensor'])
            if {'N', 'nevent', 'ncensor'} <= set(main) else
            '内訳の件数は結果値（ARD）にあります。'),
        '{感度解析の内訳}': (
            '（イベント{}例・打ち切り{}例）'.format(sens['nevent'], sens['ncensor'])
            if {'nevent', 'ncensor'} <= set(sens) else ''),
        '{感度解析の解析ID}': sid,
        '{感度解析の変数}': svar,
    }

    src = os.path.join(REPO, 'docs', *LIMITS_MD.split('/'))
    items = md_section_items(src, LIMITS_SECTION)
    if not items:
        sys.exit(f'ERROR: 前提と限界の一覧が読めない: {src} の「{LIMITS_SECTION}」')

    li = []
    for it in items:
        if any(v is None and k in it for k, v in vals.items()):
            continue
        for k, v in vals.items():
            it = it.replace(k, v or '')
        rest = re.findall(r'\{[^{}]*\}', it)
        if rest:
            sys.exit(f'ERROR: 差し込む値の名前が合わない: {"、".join(rest)}'
                     f'（{src} の「{LIMITS_SECTION}」）')
        li.append('<li>' + spec_html().inline(it, spec_link) + '</li>')
    return NL.join(li) + NL


def analysis_set_counts(rows):
    """解析対象集団ごとの例数。ARD の Out-5.1 から、集団そのものを数えた行だけを引く。

    症例の流れ図（build-flow-diagram.py）が段の例数として読むのと同じ行である。
    部分集合の行（data_subset が入る行）は集団の例数ではないので外す。
    集団の識別子は analysis_set にそのまま入っており、受入基準の id と同じ語である。
    """
    out = {}
    for r in rows:
        if (r['output_id'] == 'Out-5.1' and r['variable'] == 'DISPOSITION'
                and r['stat_name'] == 'n' and not r['data_subset']):
            try:
                out[r['analysis_set']] = int(float(r['stat_num']))
            except (TypeError, ValueError):
                pass
    return out


# README の「数値の出どころ」が、ARD の行を絞り込む鍵として案内する列。列名をここだけに
# 書き、案内の文もこの並びから組む。同梱した ARD のヘッダーと突き合わせるので、実データに
# 無い列名を案内したまま渡ることがない（C3-321）
ARD_KEYS = [('output_id', '図表番号。表番号の <code>T_</code> を <code>Out-</code> に'
                          '読み替えた形（表 5.4.1 なら <code>Out-5.4.1</code>）'),
            ('analysis_id', '解析'),
            ('variable_level', '行の水準'),
            ('group1_level', '列の水準'),
            ('stat_name', '統計量の名前')]


def ard_key_li(pkg):
    """ARD の絞り込みの案内。案内する列が同梱した ARD に実在することを確かめる"""
    p = os.path.join(pkg, 'data', 'ard', 'ard_cards_r.csv')
    if not os.path.isfile(p):
        sys.exit(f'ARD が同梱されていない: {p}')
    with open(p, encoding='utf-8-sig', newline='') as f:
        head = next(csv.reader(f))
    miss = [k for k, _ in ARD_KEYS if k not in head]
    if miss:
        sys.exit('README が案内する ARD の列が ard_cards_r.csv に無い: ' + '、'.join(miss))
    return ''.join(f'<li><code>{k}</code> … {d}</li>\n' for k, d in ARD_KEYS)


def primary_decision_li(pkg):
    """主要結論の判定を持つファイルの案内。ReportingEvent との対応を README に示す（C3-018）。

    ARS の ReportingEvent は解析の定義と結果値までを持ち、判定（閾値との比較の結果）は
    持たない。判定は解析結果ではなく解析結果に対する判断だからである。読み手が
    ReportingEvent 単体から主要結論に辿れないので、閾値の宣言と判定の記録を同じ
    16_1_9_methods へ並置し、どちらが何を持つかをここで示す。

    案内するのは同梱されているものだけにする。無いものへリンクや名前を出すと、
    自己完結の検査（check-pi-package.py）が落ちる。列の有無や値の書式には触れない
    （判定の記録は書き出した系統によって列が増減する）。
    """
    m = os.path.join(pkg, '16_1_9_methods')
    li = []
    if os.path.isfile(os.path.join(m, 'primary-endpoint.csv')):
        li.append('<li><code>16_1_9_methods/primary-endpoint.csv</code> … 閾値・評価する時点・'
                  '判定の式の宣言。値ごとにその根拠（研究計画書・統計解析計画書の節）が'
                  '入っています</li>\n')
    for p in sorted(glob.glob(os.path.join(m, 'primary_decision_*.csv'))):
        b = os.path.basename(p)
        li.append(f'<li><code>16_1_9_methods/{b}</code> … 判定の記録'
                  f'（{b[len("primary_decision_"):-len(".csv")]} 系）。推定値・信頼区間の下限・'
                  '閾値と、それに当てはめた判定が入っています</li>\n')
    return ''.join(li) or '<li>閾値の宣言と判定の記録が同梱されていない</li>\n'


def write_readme(pkg, box, rows, prim, n_acrf, narr, subj, rver):
    """入口の README。数値は写さず、値を持つ正本（宣言・metadata・図表そのもの）から組む"""
    ttl = dict(rows)

    def tlf_li(ids):
        """図表そのものが実在するものだけをリンクにする。無いものは行を出さない"""
        return ''.join(f'<li><a href="14_tlf/ja/{i}.html">{ttl[i]}</a>'
                       f' <code>{i}</code></li>\n' for i in ids if i in ttl)

    # 主要評価項目の決め方は primary-endpoint.csv が正本。項目名を日本語にするだけで、
    # 値と根拠は写さずそのまま出す
    # 根拠は節番号に限らない。信頼区間の形式は条文が無く決定記録を根拠にするので、
    # 前置きの文面も節と決定記録の両方を指す形にしてある（C3-312）
    PE_LABEL = {'analysis_id': '評価する解析', 'timepoint': '評価する時点',
                'threshold': '閾値', 'ci_method': '信頼区間の求め方',
                'comparison': '判定（lcl は信頼区間の下限）'}
    primary_def = ''.join(
        f'<li>{PE_LABEL.get(r["item"], r["item"])} … <code>{r["value"]}</code>'
        f'　（{r["source"]}）</li>\n' for r in meta_rows('primary-endpoint.csv', ACC))
    # 集団の人数は症例の流れ図と同じ ARD から引き、受入基準の期待値と突き合わせる。
    # 別々の出どころから出したまま並べると、片方だけが古くなっても気付けない（C3-314）。
    # 流れ図はこれより先に組み、R 系の ARD が無ければそこで止まっている
    n_set = analysis_set_counts(ard_rows(box))

    def set_n(r):
        got = n_set.get(r['id'])
        exp = r.get('n_expected', '').strip()
        if got is None:
            sys.exit(f'ARD の Out-5.1 に解析対象集団 {r["id"]} の例数が無い')
        if exp and int(exp) != got:
            sys.exit(f'解析対象集団 {r["id"]} の例数が食い違う: ARD {got}例 / '
                     f'analysis-set-condition.csv {exp}例')
        return got

    sets = ''.join(
        f'<li><code>{r["id"]}</code>　{set_n(r)}例　{r["note"]}</li>\n'
        for r in meta_rows('analysis-set-condition.csv', ACC) if r['kind'] == 'analysisSet')
    # 症例の流れを見る図表。番号（5.1・5.1.1・5.1.2）は解析計画の節番号で、宣言が持つ
    flow = tlf_li(['T_5_1', 'T_5_1_1', 'T_5_1_2'])
    # 登録から解析対象までを1枚にした図と、方法と結果を文章で述べた記述（C2-108）。
    # 同梱できたかは写しの実在で決める。無いものへリンクを出すと自己完結の検査が落ちる
    flow = ''.join(
        f'<li><a href="16_1_9_methods/{f}">{t}</li>\n' for f, t in
        (('subject-flow.html',
          '症例の流れ図</a> … 登録から解析対象集団までと、試験治療・試験の転帰を1枚に'
          'まとめた図です（英語版は <code>subject-flow-en.html</code>）'),
         ('statistical-methods-and-results.html',
          '統計手法と結果の記述</a> … どの集団にどの方法を当て、結果がどうなったかを'
          '文章で述べたものです'))
        if os.path.isfile(os.path.join(pkg, '16_1_9_methods', f))) + flow
    open_btn = ''.join(
        f'<a class="big" href="{h}">{t}</a>\n' for h, t in
        ([(f'14_tlf/ja/{prim[0]}.html', '主要評価項目の表をひらく')] if prim and prim[0] in ttl
         else [])
        + ([(f'14_tlf/ja/{prim[1]}.html', '主要評価項目の図をひらく')]
           if len(prim) > 1 and prim[1] in ttl else [])
        + [('14_tlf/index.html', '図表の一覧をひらく'),
           ('traceability.html', 'トレーサビリティ索引をひらく'),
           ('16_1_2_acrf/index.html', 'CRF をひらく')])
    html = (README.replace('__TRIAL__', boxpath.trial_id())
            .replace('__DATE__', datetime.date.today().strftime('%Y-%m-%d'))
                  .replace('__OPEN__', open_btn)
                  .replace('__PRIMARYDEF__', primary_def)
                  .replace('__PRIMARYRESULT__', primary_result(box))
                  .replace('__PRIMARYLINK__', tlf_li(prim))
                  .replace('__SETS__', sets)
                  .replace('__FLOW__', flow or '<li>症例の流れの表が同梱されていない</li>\n')
                  .replace('__LIMITS__', limits_block(box))
                  .replace('__CUT__', data_snapshot(box))
                  .replace('__RVER__', rver)
                  .replace('__CONTACT__', contact_block())
                  .replace('__NACRF__', str(n_acrf))
                  .replace('__SAP__', SAP_LI)
                  .replace('__ARDKEYS__', ard_key_li(pkg))
                  .replace('__PRIMARYDECISION__', primary_decision_li(pkg))
                  .replace('__NARR__', narr)
                  .replace('__SUBJ__', subj)
                  .replace('__REPRODUCE__', '受領CSV から図表までを実際に走らせられます。'))
    open(os.path.join(pkg, 'README.html'), 'w', encoding='utf-8', newline='\n').write(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', help='パッケージを作る場所（既定は Box の output/deliver/r/）')
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
    n_svg = 0
    for lang in ('ja', 'en'):
        src = os.path.join(box, 'output', 'tlf', 'r-' + lang)
        if not os.path.isdir(src):
            sys.exit(f'{src} が無い。先に Rscript program/r/{boxpath.trial_id()}_TLF.R を回す。')
        # 図表ごとの HTML だけを拾う。同じディレクトリに通し読み HTML も置くため
        n_fig[lang] = (copy_tlf(src, os.path.join(pkg, '14_tlf', lang), 'T_*.html')
                       + copy_tlf(src, os.path.join(pkg, '14_tlf', lang), 'F_*.html'))
        # 図はベクター形式の SVG としても渡す（C2-112）。論文へ出すときに HTML から
        # 取り出さずに済む。中身は図表 HTML に埋まっている SVG と同じもの（TLF.R が書く）
        for p in sorted(glob.glob(os.path.join(src, 'figures', 'F_*.svg'))):
            copy(p, os.path.join(pkg, '14_tlf', lang, 'figures', os.path.basename(p)))
            n_svg += 1
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
          f'通し読み {n_doc}、Excel {n_xl}、図の SVG {n_svg}')

    # --- 14.3.3 重篤な有害事象の経過（narratives） ---
    n_nar, n_ev, n_sub = copy_narratives(box, os.path.join(pkg, '14_3_3_narratives'))
    narr = ('<li><code>14_3_3_narratives/</code> … 重篤な有害事象の経過（narratives）。'
            f'{n_ev}件・{n_sub}症例。'
            '<a href="14_3_3_narratives/index.html">この節の説明</a>から開きます。'
            '施設が入力した自由記述が原文のまま入っています</li>') if n_nar else ''

    # --- 16.1.2 注釈付き CRF ---
    src, ng = acrf_source(box, a.acrf_dir, a.refresh_acrf)
    dst = os.path.join(pkg, '16_1_2_acrf')
    shutil.copytree(src, dst, dirs_exist_ok=True)
    n_acrf = len(glob.glob(os.path.join(dst, '*.html')))
    write_acrf_index(dst)
    n_nav = add_acrf_nav(dst)
    print(f'  16_1_2_acrf: {n_acrf} 帳票' + (f'（取得できず {ng}）' if ng else '')
          + f'。戻りリンクを {n_nav} 帳票へ足した')

    # --- 16.1.9 統計手法の記録 ---
    m = os.path.join(pkg, '16_1_9_methods')
    n_m = 0
    for src, dst, lay in ((os.path.join(box, 'datasets', 'define', 'sdtm', 'define.html'),
                           'define_sdtm.html', 'sdtm'),
                          (os.path.join(box, 'datasets', 'define', 'adam', 'define.html'),
                           'define_adam.html', 'adam')):
        if os.path.exists(src):
            # define.html はデータセット（Dataset-JSON）へ隣のファイルとしてリンクしている。
            # パッケージでは data/<層>/ に置くので相対パスを差し替える。
            t = open(src, encoding='utf-8', errors='replace').read()
            t = re.sub(r'href="([a-z0-9_]+\.json)"',
                       lambda x: f'href="../data/{lay}/{x.group(1)}"', t)
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
    # 固定版 SAP（規制文書。実装の仕様である analysis-dataset-design・efs-derivation と並べて置く）
    n_m += copy_sap_pdf(m)
    # 二重作成の突合。結果のファイルを同梱し、合否を1枚にまとめる（C2-079・C2-110）
    n_m += write_double_coding(m, box)
    # 症例の流れ図（CONSORT 様式。日本語版と英語版）。数値は写さず ARD から組む（C2-108）
    before = set(glob.glob(os.path.join(m, '*.html')))
    sh(sys.executable, os.path.join(SCRIPTS, 'build-flow-diagram.py'), '--out-dir', m, '--quiet')
    n_m += len(set(glob.glob(os.path.join(m, '*.html'))) - before)
    # 受け取った側が最初に開く1点。PHUSE の ADRG・SDRG の様式に合わせた案内と、
    # 総括報告書 §9.8.3・§16.1.9 の原稿。いずれも決定記録と宣言から組み立てる生成物で、
    # 値も文言も写さない。define.xml はデータセットのラベルを引くために渡す
    before = set(glob.glob(os.path.join(m, '*.html')))
    rg = [sys.executable, os.path.join(SCRIPTS, 'build-reviewers-guide.py'),
          '--out-dir', m, '--quiet']
    adef = os.path.join(pkg, 'data', 'adam', 'define.xml')
    if os.path.exists(adef):
        rg += ['--define', adef]
    sh(*rg)
    n_m += len(set(glob.glob(os.path.join(m, '*.html'))) - before)
    # ARS の ReportingEvent。解析の定義と結果値が CDISC の標準形式で1つに入っている。
    # ARS を入力とするツール（TFL Designer 等）に載せられ、将来の再利用にも効く。
    # 被験者単位の情報は含まない（集計値のみ）。docs/validation/ard-double-coding-spec.md。
    for sysname in ('sas', 'r'):
        src = os.path.join(box, 'datasets', sysname, 'ard',
                           f'reporting-event-{sysname}.json')
        if os.path.exists(src):
            copy(src, os.path.join(m, os.path.basename(src)))
            n_m += 1
    # 閾値の宣言。ReportingEvent は解析の定義と結果値までを持ち、判定（閾値との比較の結果）は
    # 持たない。判定は解析結果ではなく解析結果に対する判断だからである。判定の記録
    # （primary_decision_<系統>.csv）は write_double_coding が同じフォルダへ写しているので、
    # 宣言をここへ並置すると ReportingEvent と同じフォルダの中で主要結論が突き合わせられる。
    # 写す元はリポジトリが持つので無ければ copy が落ちる（C3-018）
    copy(os.path.join(REPO, 'docs', *ACC.split('/'), 'primary-endpoint.csv'),
         os.path.join(m, 'primary-endpoint.csv'))
    n_m += 1
    print(f'  16_1_9_methods: {n_m} ファイル')

    # --- data（ARD は集計値なので既定で入れる） ---
    # ARD の置き場は datasets/<系統>/ard/。2026-08-30 まで datasets/sas/adam/ を見ており、
    # そこに残っていた古い写し（R 系1本）だけが入っていた。同じディレクトリにある
    # reporting-event-<系統>.json は 16_1_9_methods へ別に写すので、ここでは拾わない
    n_d = []
    for sysname in ('sas', 'r'):
        for p in sorted(glob.glob(os.path.join(box, 'datasets', sysname, 'ard',
                                               'ard_cards*.csv'))):
            copy(p, os.path.join(pkg, 'data', 'ard', os.path.basename(p)))
            n_d.append(f'{sysname}:{os.path.basename(p)}')
    print(f'  data/ard: {len(n_d)} ファイル（{"、".join(n_d) if n_d else "見つからない"}）')

    # --- reproduce（R 一式と仕様ファイル） ---
    # 写し先はリポジトリと同じ相対位置にする（2026-08-31）。組み立て時に位置を変えると、
    # 同梱したスクリプトが自分の位置から辿る先とズレ、パッケージの中で動かなくなる。
    # R のソースは .progdir（自分の位置）から source するので中身は変えなくてよい。
    n_r = copy_tree(os.path.join(REPO, 'program', 'r'),
                    os.path.join(pkg, 'reproduce', 'program', 'r'), '*.R')
    # 版の固定。lock だけでなく renv の活性化2ファイルも入れる。配った先で reproduce/ を
    # 起点に R を開くと renv が自分を取ってきて .libPaths を差し替えるので、
    # renv::restore() だけで lock と同じ版が揃う（PI に renv の導入手順を要求しない）
    copy(os.path.join(REPO, 'renv.lock'), os.path.join(pkg, 'reproduce', 'renv.lock'))
    copy(os.path.join(REPO, '.Rprofile'), os.path.join(pkg, 'reproduce', '.Rprofile'))
    write_run_r(pkg, boxpath.trial_id())
    copy(os.path.join(REPO, 'renv', 'activate.R'),
         os.path.join(pkg, 'reproduce', 'renv', 'activate.R'))
    n_spec = 0
    # 機械が読む定義・受入基準・試験の設定は、リポジトリと同じ相対位置へそのまま写す。
    # 2026-08-30 まで input/spec/ へ平らに写し、trial.json は box_path を落として書き出して
    # いたが、どちらもやめた（2026-08-31）。位置を変えると同梱スクリプトの自己解決が
    # 壊れ、内容を変えると正本と違う写しがもう1つできる。
    #   trial.json … 同梱しないと配った先で図表の描画が「trial.json が見つかりません」で
    #     止まる（2026-08-29）。box_path を落としていたのは秘匿のためとしていたが、同じ並びは
    #     16_1_9_methods の仕様 HTML に外部データの出どころとして本文へ印字されており、
    #     check-pi-package.py の SECRET も絶対パスとユーザー名だけを対象にしている。
    #     隠せていない一方で、落とすと boxpath.py が import の時点で落ちていた。
    #   external/ars-v1-0.schema.json … check-ars-json.py がパッケージの中で動くために要る。
    # 写すものは選ぶ。docs/metadata/ を丸ごと写してはいけない（delivery-contact.csv は
    # 納品先の連絡先、core-issue-disposition.csv は仕分けの作業記録）。
    # 2026-09-05（段F）に define.xml の生成用も入れることへ改めた。それまでは
    # 「生成用だから要らない」として外していたが、SDTM の define.xml をこの一式の中で
    # 作り直せるようにしたので、生成が読むものは入れなければ手順が閉じない。
    # 入れるのは SDTM 側が読む5本（sdtm-value-level・sdtm-codelist-values・
    # sdtm-codelist-mode・codelist-decode と external の IG・CT）で、adam-codelist.csv は
    # 外したまま残す。ADaM の生成の本体がスキルにあり、CSV を渡しても作り直せないため。
    # 写す元が無ければ copy が落ちる
    for sub, names in (
        ('metadata', ('trial.json',
                      'tlf-index.csv', 'label-catalog.csv', 'variable-map.csv',
                      # SDTM のデータセットのラベルと OID。CSVtoSDTM.R が読む（C3 段B）
                      'sdtm_datasets.csv',
                      'crf-field-map.csv', 'crf-option-map.csv',
                      'reference-table-rows.csv', 'reference-values.csv',
                      'mr-timepoint.csv',
                      # 集計の水準集合の正本。tlf_ops.R が読み込み時に要求する（C3-002）
                      'level-sets.csv',
                      # ARS の ReportingEvent を組み立てる宣言（C2-145）
                      'analysis-purpose.csv', 'analysis-grouping.csv',
                      'method-code.csv',
                      'reference-documents.csv',
                      # SDTM の define.xml の生成が読む宣言（段F）
                      'sdtm-value-level.csv', 'sdtm-codelist-values.csv',
                      'sdtm-codelist-mode.csv', 'codelist-decode.csv')),
        ('metadata/trial-design', ('ta.csv', 'te.csv', 'ti.csv', 'ts.csv', 'tv.csv')),
        # sdtm_variable_order.csv … SDTM の標準変数順。CSVtoSDTM.R と define.xml の生成が
        #   読む。2026-09-05 に input/ext から移したので、input/ext の写しでは配った先に
        #   届かない（C3 段B）
        # sdtmig-3-2-variable-roles.csv・ct-domain-ccode.csv … define.xml の生成が読む
        #   外部標準の写し（段F）
        ('metadata/external', ('ars-v1-0.schema.json', 'sdtm_variable_order.csv',
                               'sdtmig-3-2-variable-roles.csv', 'ct-domain-ccode.csv')),
        # 受入基準（2026-08-31 に docs/metadata/ から移した）。主要評価項目の判定を
        # 組み立てる tlf_ops.R と、図表の期待値を照合する CompareTLF.R が読む
        (ACC, ('primary-endpoint.csv', 'analysis-set-condition.csv',
               'display-contract.csv')),
    ):
        for name in names:
            copy(os.path.join(REPO, 'docs', *sub.split('/'), name),
                 os.path.join(pkg, 'reproduce', 'docs', *sub.split('/'), name))
            n_spec += 1
    # R のコメントは仕様書を `docs/<名前>.md` で指す。R を回す起点が reproduce/ なので、
    # その直下に docs/ を置けば配った先でも同じ相対パスで辿れる（16_1_9_methods の HTML は
    # 読み物としての同じ内容で、正本はこの md。CLAUDE.md「文書の正本」）。同梱するものは
    # R の中身から集める。一覧を別に持つとコメントを直したときにズレるため。
    # 同梱した md が指す md も辿る。`docs/spec/adam-spec.md` は時間イベントの導出とデータセットの
    # 構成の正本として `docs/records/efs-derivation.md`・`analysis-dataset-design.md` を指しており、
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

    def drop_links(text, here):
        """同梱しない md へのリンクを、素の文字列へ落とす。

        許可の外にある文書を指したまま写すと、パッケージの中で参照先が無くなり
        自己完結の検査が落ちる。参照していた事実は残したいので、リンクの記法だけを
        外して題名を本文に残し、同梱していない旨を添える
        （docs/reporting/traceability-design.md「納品物に入れてよい文書の境界」）。
        """
        def rep(m):
            label, target = m.group(1), m.group(2)
            ref = os.path.normpath(os.path.join(here or '', target)).replace(os.sep, '/')
            if doc_allowed(ref):
                return m.group(0)
            return label + '（内部の記録のため同梱していない）'
        return re.sub(r'\[([^\]]+)\]\(([\w.\-/]+\.md)\)', rep, text)

    pending = []
    for p in sorted(glob.glob(os.path.join(pkg, 'reproduce', 'program', 'r', '*.R'))):
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
    # 索引を作り直す Python 一式と、作り直した図表を突き合わせる納品時のセル台帳
    n_trace = copy_trace_scripts(pkg)
    n_exp = copy_expected(pkg, box)
    print(f'  reproduce: R {n_r} 本 + 仕様 {n_spec} ファイル + docs {n_doc} ファイル'
          + f' + 索引の生成 {n_trace} ファイル + define の生成 {len(DEFINE_SCRIPTS)} ファイル'
          + f' + 突合の台帳 {n_exp} ファイル'
          + (f'（同梱しなかった参照 {len(set(lost))} 件: {sorted(set(lost))}）' if lost else ''))

    # --- 被験者単位のデータ ---
    # 区分けを設けず必ず入れる。研究責任医師は試験データの所有者で、統計解析は預かっている
    # 側にすぎない。預かる側が所有者へ返すものを絞る理由が無く、境界を引けば必ずズレる
    # （2026-08-30 の判断。docs/validation/records/codex-review-2-ledger.md の C2-073）
    c = 0
    for lay, src in (('sdtm', os.path.join(box, 'datasets', 'r', 'sdtm', 'json')),
                     ('adam', os.path.join(box, 'datasets', 'r', 'adam', 'json'))):
        if os.path.isdir(src):
            c += copy_tree(src, os.path.join(pkg, 'data', lay), '*.json')
    # データセットの定義（define.xml）。読み物としての define.html は 16_1_9_methods/ に
    # 入れてあるが、機械が読む形も要る。索引を作り直すとき、変数のキーをここから読む
    # （reproduce/scripts/rebuild-traceability.py）。データセットのラベルは
    # docs/metadata/sdtm_datasets.csv が正本なので reproduce/docs/metadata/ の1組で足りる。
    # define.xml は表示用の XSL を <?xml-stylesheet?> で隣のファイルとして指すので、XSL も
    # 同じフォルダへ写す。写さないと、PI が define.xml を直接開いたときスタイルの当たらない
    # 生の XML が出る（2026-09-05 に発見。段E）
    for lay, name in (('sdtm', 'define.xml'), ('sdtm', 'define2-0-0.xsl'),
                      ('adam', 'define.xml'), ('adam', 'define2-0-0.xsl')):
        src = os.path.join(box, 'datasets', 'define', lay, name)
        if os.path.exists(src):
            copy(src, os.path.join(pkg, 'data', lay, name))
            c += 1
    for src, dst in ((os.path.join(box, 'input', 'rawdata'),
                      os.path.join(pkg, 'reproduce', 'input', 'rawdata')),
                     (os.path.join(box, 'input', 'ext'),
                      os.path.join(pkg, 'reproduce', 'input', 'ext'))):
        if os.path.isdir(src):
            c += copy_tree(src, dst, '*.csv')
    # 受領 define.xml と、それが指す表示用の XSL。SDTM の define.xml を作り直す材料で、
    # Origin 305件・CodeList 100件・EnumeratedItem 2062件・ValueListDef 7・WhereClauseDef 72・
    # MethodDef 3・def:leaf 17 はここにしか無い（2026-09-05。段F）。受領物をどこまで渡すかの
    # 判断にあたるが、被験者単位データを区分けなく入れたのと同じ扱いにする（C2-073）。
    # 受領時の階層のまま写す。フォルダ名が固定データの回と受領の日時を持っており、
    # 平らにすると出どころが名前から消える。生成側も同じ相対パスで探す（trial.json）。
    rel = boxpath.received_define_rel()
    src = os.path.join(box, rel)
    if not os.path.isdir(src):
        raise SystemExit(f'受領 define.xml のフォルダが無い: {src}')
    c += copy_tree(src, os.path.join(pkg, 'reproduce', rel))
    if c == 0:
        raise SystemExit('被験者単位データが1件も見つからない。Box の datasets と input を確認する')
    n_ds, n_row = write_listings(pkg, box)
    print(f'  被験者単位データ: {c} ファイル / 16.2 の一覧 {n_ds} 本・{n_row:,} 行')
    # 取り扱いの条件は、条件が掛かる同梱物の案内と同じ行に置く。問い合わせ先の節に
    # 置いていたときは、条件が問い合わせた人にだけ掛かるように読めた（2026-09-05。C3-323）
    subj = ('<li><code>data/sdtm</code>・<code>data/adam</code>・'
            '<code>reproduce/input</code> … 被験者単位のデータ。個別の被験者に結び付く'
            '情報を含むため、受け取った人の範囲を超えて再共有せず、この試験の解析と報告'
            '以外の目的に使わないでください</li>')

    # --- 実行環境の記録（renv.lock が持たない OS・ロケール・文字コード） ---
    rver = write_environment(pkg)

    # --- 再現の手順（入力・実行の順・成功の判定・つまずいたとき） ---
    write_reproduce_guide(pkg, box, rver, n_trace, n_exp)

    # --- トレーサビリティ索引（相対パスを E3 の階層に合わせて作り直す） ---
    # 索引の整合（到達率・つながっていない箇所）は画面に出さない作りなので、JSON で受け取って
    # 検証の記録へ載せる。生成時のログしか無いと、PI からは完全性が見えない
    tmp = tempfile.mkdtemp(prefix='pi-pkg-')
    qcj = os.path.join(tmp, 'traceability-qc.json')
    o = sh(sys.executable, os.path.join(SCRIPTS, 'build-traceability.py'),
           '--out', os.path.join(pkg, 'traceability.html'),
           '--acrf-base', '16_1_2_acrf', '--tlf-base', '14_tlf/ja', '--qc-json', qcj)
    for line in (o or '').splitlines():
        if line.startswith(('aCRF:', '図表:', '  同梱')):
            print('  ' + line)
    add_index_fallback(os.path.join(pkg, 'traceability.html'))

    # --- 図表の一覧（静的な目次。索引が開けないときの入口でもある） ---
    rows = tlf_order(pkg)
    whole = sorted(os.path.basename(p) for p in
                   glob.glob(os.path.join(pkg, '14_tlf', '*.html'))
                   if os.path.basename(p) != 'index.html')
    prim = primary_ids()
    write_tlf_index(pkg, rows, whole, set(prim))
    print(f'  14_tlf/index.html: {len(rows)} 件の一覧'
          + (f'（主要評価項目 {"・".join(prim)}）' if prim else '（主要評価項目が引けない）'))

    # --- README ---
    write_readme(pkg, box, rows, prim, n_acrf, narr, subj, rver)

    # フォルダごとどこへ置いても動くか（相対リンクだけで閉じているか）をその場で確かめる。
    # 結果は検証の記録へ載せるので、記録とマニフェストを作る前に1度回す
    print('--- 自己完結の検査 ---')
    # 検証の記録と同梱物の一覧は、この検査の結果を載せるので後に作る。README は先に
    # それらを指しているので、1回目だけ未作成を許す（作った後の2回目で確かめ直す）
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'check-pi-package.py'), pkg,
                        '--pending', 'manifest.html,manifest.csv,'
                        '16_1_9_methods/validation-report.html'],
                       capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    print((r.stdout or '').rstrip())
    if r.returncode:
        print((r.stderr or '')[-1000:])
        sys.exit('パッケージの中にパッケージ外を指すリンクがある')

    # --- 検証の記録と同梱物の一覧（ここまでの結果を載せるので最後に作る） ---
    write_validation_report(pkg, o or '', r.stdout or '', qcj)
    shutil.rmtree(tmp, ignore_errors=True)
    n_man, size = write_manifest(pkg)
    print(f'できた: {pkg}（{n_man} ファイル・{size / 1e6:.1f} MB。'
          f'ほかに同梱物の一覧 {len(MANIFEST)} 件）')

    # 記録と一覧を足した後の状態でもう一度確かめる（足したリンクが切れていないか）
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'check-pi-package.py'), pkg],
                       capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    print((r.stdout or '').rstrip().splitlines()[-1] if r.stdout else '')
    if r.returncode:
        print((r.stdout or '')[-2000:])
        sys.exit('検証の記録・同梱物の一覧を足した後の検査で誤りが出た')


if __name__ == '__main__':
    main()
