# build-reviewers-guide.py
#
# 納品パッケージの入口となる3つの読み物を組み立てる。いずれも生成物で、手で書かない。
# 材料は正本のファイルだけを読み、値を写さない。
#
#   analysis-data-reviewers-guide.html  解析データの案内（ADRG）
#   study-data-reviewers-guide.html 受領データの案内（SDRG）
#   csr-deviations.html             総括報告書 §9.8.3 と §16.1.9 の原稿
#
# 節立ては PHUSE の様式に合わせる。ADRG が7節（Introduction・Protocol Description・
# Analysis Considerations Related to Multiple Analysis Datasets・Analysis Data Creation
# and Processing Issues・Analysis Dataset Descriptions・Data Conformance Summary・
# Submission of Programs）、SDRG が4節（Introduction・Protocol Description・
# Subject Data Description・Data Conformance Summary）である。試験ごとに節を作らない。
#
# ADRG は protocol・SAP・define.xml・CSR にある情報を限定して重複させ、受け取った側が
# 最初に開く1点を作るための文書である（PHUSE の様式がその位置づけを明記している）。
# 重複を手で書くと片方が古くなるので、正本から組み立てる形にした。
#
# 逸脱と補完の区分は docs/decisions/data-handling-decisions.md の各エントリが持つ。
# ICH E3 は §9.8.3 を Changes in the Planned Analyses、§16.1.9 を統計手法の文書とする。
#
# 使い方
#   python scripts/build-reviewers-guide.py --out-dir <dir>
#   python scripts/build-reviewers-guide.py --out-dir <dir> --define <ADaM の define.xml>
import argparse
import csv
import html
import importlib.util
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding='utf-8')

SCRIPTS = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    """ハイフンを含むファイル名のスクリプトを読み込む"""
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 体裁は build-spec-html.py の CSS を使う。同じフォルダに並ぶ読み物なので、
# 見た目の正本を2つ持たない
CSS = _load('_spec_html', 'build-spec-html.py').CSS

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(REPO, 'docs')
NL = '\n'

REG = os.path.join(DOCS, 'decisions', 'data-handling-decisions.md')
FRAME = ('区分', '識別子', '一覧')


def esc(s):
    return html.escape(str(s))


def rows(path, sub='metadata'):
    p = path if os.path.isabs(path) else os.path.join(DOCS, sub, path)
    with open(p, encoding='utf-8-sig', newline='') as fh:
        return list(csv.DictReader(fh))


def trial():
    with open(os.path.join(DOCS, 'metadata', 'trial.json'), encoding='utf-8') as fh:
        return json.load(fh)


def entries():
    """台帳のエントリ。見出しと区分の3つ、本文の最初の段落"""
    t = open(REG, encoding='utf-8').read().replace('\r\n', NL)
    out, cur, buf = [], None, []
    for line in t.split(NL):
        if line.startswith('## '):
            if cur:
                cur['body'] = buf
                out.append(cur)
            name = line[3:]
            cur = {'name': name} if name not in FRAME else None
            buf = []
        elif cur is not None:
            for k, lab in (('区分', '- 区分：'), ('決め方', '- 決め方：'), ('CSR', '- CSR：')):
                if line.startswith(lab):
                    cur[k] = line[len(lab):]
                    break
            else:
                # 小見出し（移設前からある16件が持つ「### 決定」など）と箇条書きの記号は
                # 本文として拾わない。拾うと案内の一文が見出しの文字列になる
                if line.strip() and not line.startswith('#'):
                    buf.append(line.lstrip('- ').strip())
    if cur:
        cur['body'] = buf
        out.append(cur)
    return out


def lead(e, n=1):
    """エントリの本文の先頭 n 段落。リンク記法は文字だけに落とす"""
    txt = ' '.join(e.get('body', [])[:n])
    txt = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', txt)
    return txt


def define_labels(path):
    """define.xml の ItemGroupDef から データセットのラベルを引く"""
    if not path or not os.path.exists(path):
        return {}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return {}
    ns = {'o': 'http://www.cdisc.org/ns/odm/v1.3'}
    out = {}
    for ig in root.iter():
        if not ig.tag.endswith('ItemGroupDef'):
            continue
        name = ig.get('Name')
        for d in ig:
            if d.tag.endswith('Description'):
                for tx in d:
                    if tx.tag.endswith('TranslatedText') and tx.text:
                        out[name] = tx.text.strip()
    del ns
    return out


def page(title, subtitle, body):
    return (('<!doctype html>' + NL + '<html lang="ja"><head><meta charset="utf-8">'
             '<meta name="viewport" content="width=device-width,initial-scale=1">'
             '<title>%s</title><style>%s</style></head><body>' % (esc(title), CSS))
            + NL + '<header><div class="in"><span class="doc">%s</span>' % esc(title)
            + '<a class="back" href="../README.html">最初のページへ戻る</a></div></header>'
            + NL + '<main><h1>%s</h1>' % esc(title)
            + (('<p class="note">%s</p>' % subtitle) if subtitle else '')
            + NL + body
            + NL + '<p><a href="../README.html">最初のページへ戻る</a></p>'
            + NL + '</main></body></html>' + NL)


def ul(items):
    return '<ul>' + ''.join('<li>%s</li>' % x for x in items) + '</ul>'


# --- 共通の節 -------------------------------------------------------------------

def sec_protocol(t):
    pe = {r['item']: r for r in rows('../validation/acceptance/primary-endpoint.csv')}
    sets = [r for r in rows('../validation/acceptance/analysis-set-condition.csv')
            if r.get('kind') == 'set' and r.get('n_expected')]
    b = ['<h2>2. Protocol Description</h2>']
    b.append('<p>試験の識別子は <code>%s</code> です。研究計画書と統計解析計画書が'
             '解析の要求の正本で、この文書はそこから組み立てた写しです。'
             '節番号での参照は <a href="ard-spec.html">ARD 解析仕様</a>が持ちます。</p>'
             % esc(t['trial_id']))
    b.append('<h3>主要評価項目の判定</h3>')
    b.append(ul(['%s … <code>%s</code>（%s）'
                 % (esc(k), esc(pe[k]['value']),
                    esc(re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', pe[k]['source'])))
                 for k in ('analysis_id', 'timepoint', 'threshold', 'ci_method',
                           'comparison', 'estimate_operation') if k in pe]))
    if sets:
        b.append('<h3>解析対象集団</h3>')
        b.append(ul(['<code>%s</code> … %s 例%s'
                     % (esc(r['id']), esc(r['n_expected']),
                        '（%s）' % esc(r['note']) if r.get('note') else '')
                     for r in sets]))
        b.append('<p>判定の条件は '
                 '<a href="analysis-population-derivation.html">解析対象集団の導出</a>、'
                 '機械が読む宣言は <code>reproduce/docs/validation/acceptance/'
                 'analysis-set-condition.csv</code> が持ちます。</p>')
    return NL.join(b)


def sec_conformance(n):
    disp = rows('core-issue-disposition.csv')
    kinds = {}
    for r in disp:
        kinds[r['disposition']] = kinds.get(r['disposition'], 0) + 1
    b = ['<h2>%d. Data Conformance Summary</h2>' % n]
    b.append('<p>受領した SDTM と作成した ADaM に CDISC CORE をかけ、指摘を1件ずつ'
             '仕分けています。仕分けの正本は <code>reproduce/docs/metadata/'
             'core-issue-disposition.csv</code> で、件数はそれを数えて得ます。</p>')
    b.append(ul(['%s … %d 件' % (esc(k), v) for k, v in sorted(kinds.items())]))
    b.append('<p>指摘ごとの理由は'
             '<a href="../reproduce/docs/validation/records/'
             'sdtm-conformance-findings-20260815.md">適合性検証の記録</a>、'
             '検証の全体は<a href="validation-report.html">検証の記録</a>にあります。</p>')
    return NL.join(b)


# --- ADRG ------------------------------------------------------------------------

def adrg(t, labels):
    ents = entries()
    dev = [e for e in ents if e.get('区分') == '逸脱']
    post = [e for e in ents if e.get('区分') == '補完' and e.get('決め方') == '固定データ']
    vm = rows('variable-map.csv')
    ad = {}
    for r in vm:
        if r['layer'] == 'adam':
            ad.setdefault(r['dataset'], 0)
            ad[r['dataset']] += 1
    ext = sorted(f for f in os.listdir(os.path.join(DOCS, 'input'))
                 if f.endswith('-external-data-spec.md'))

    b = []
    b.append('<h2>1. Introduction</h2>')
    b.append('<p>解析データセットを読むための案内です。PHUSE の Analysis Data '
             'Reviewer’s Guide の様式に合わせて7節で書いています。研究計画書・'
             '統計解析計画書・define.xml・総括報告書にある情報を限定して重ねてあり、'
             '最初に開く1点として使えるようにしたものです。</p>')
    b.append('<p>この文書は生成物です。正本は '
             '<a href="data-handling-decisions.html">データ取り扱い決定記録</a>と'
             '各仕様書、<code>reproduce/docs/metadata/</code> の宣言で、'
             'ここには値を写していません。</p>')

    b.append(sec_protocol(t))

    b.append('<h2>3. Analysis Considerations Related to Multiple Analysis Datasets</h2>')
    b.append('<p>データセットをまたぐ考慮事項です。</p>')
    # 下の箇条のうち、時間イベントのパラメータ名と、正本として指す仕様書の名前は試験固有。
    # 節立て（PHUSE の様式）は試験に依存しないので汎用層が持つが、中身は新しい試験で
    # 自分の導出仕様から起こし直す。
    b.append(ul([
        'すべての解析データセットは <code>ADSL</code> の解析対象集団フラグで絞ります。'
        '集団の定義は<a href="analysis-population-derivation.html">解析対象集団の導出</a>。',
        '時間イベント（EFS・OS・RFS・CIR・NRM）の起算日・イベント・打ち切りは'
        '<a href="efs-derivation.html">EFS の解析計画</a>が正本で、'
        '<code>ADTTE</code> の全パラメータが同じ規則に従います。',
        'SDTM 層で決めた値は ADaM 層で再計算しません（'
        '<a href="adam-spec.html">ADaM 作成仕様</a> §1.1）。',
        'SAS 系と R 系で独立に実装し、結果値を突き合わせています。'
        '突合の設計は<a href="ard-double-coding-spec.html">二重作成の仕様</a>、'
        '結果は<a href="double-coding-report.html">二重作成の突合</a>。',
    ]))

    b.append('<h2>4. Analysis Data Creation and Processing Issues</h2>')
    b.append('<p>受領データから解析データセットを作る過程で判断を要した事項です。'
             '判断は1つの台帳に集めてあり、各件が「一次文書が答えを持つか」と'
             '「何を見て決めたか」の2つで分かれています。'
             '一覧は<a href="data-handling-decisions.html">データ取り扱い決定記録</a>。</p>')
    b.append('<h3>統計解析計画書からの逸脱</h3>')
    b.append('<p>条文があるのに実装が違うものが %d 件あります。'
             '総括報告書での扱いは<a href="csr-deviations.html">'
             '総括報告書の原稿</a>にあります。'
             '各件の条文・実装・理由は台帳の同じ見出しが持ちます。</p>' % len(dev))
    # 本文の抜粋は載せない。エントリの先頭段落は、決定ではなく解こうとした問題を
    # 述べていることがあり（C-1・C-7）、抜粋すると決定を取り違えて伝える
    b.append(ul(['<a href="data-handling-decisions.html">%s</a>（%s）'
                 % (esc(e['name']), esc(e.get('決め方', ''))) for e in dev]))
    b.append('<h3>固定データを見てから決めた補完</h3>')
    b.append('<p>条文が答えを持たず、観測した件数や欠測を見て決めたものが %d 件'
             'あります。事後の判断にあたるので、結果を読むときの前提になります。</p>'
             % len(post))
    b.append(ul([esc(e['name']) for e in post]))
    if ext:
        b.append('<h3>外部データ</h3>')
        b.append('<p>症例報告書に記録の場所が無い項目を、出所を特定できる記録から'
                 '補っています。補ってよい条件は決定記録の'
                 '「データベース固定後に記録されていない情報の取り扱い」が持ちます。</p>')
        b.append(ul(['<a href="%s">%s</a>' % (esc(f[:-3] + '.html'), esc(f))
                     for f in ext]))

    b.append('<h2>5. Analysis Dataset Descriptions</h2>')
    b.append('<p>解析データセットは %d 本です。変数の由来は '
             '<code>data/adam/define.xml</code>（表示用は '
             '<a href="define_adam.html">ADaM の define</a>）が持ちます。</p>' % len(ad))
    b.append(ul(['<code>%s</code>%s … 変数 %d'
                 % (esc(k), '（%s）' % esc(labels[k]) if k in labels else '', v)
                 for k, v in sorted(ad.items())]))
    b.append('<p>構成と役割は'
             '<a href="analysis-dataset-design.html">解析データセットの設計</a>、'
             '変数ごとの導出は<a href="adam-spec.html">ADaM 作成仕様</a>。</p>')

    b.append(sec_conformance(6))

    b.append('<h2>7. Submission of Programs</h2>')
    b.append('<p>解析を走らせ直す一式は <code>reproduce/</code> に入っています。'
             '手順は<a href="../reproduce/README.html">再現の手順</a>が入口です。</p>')
    b.append(ul([
        '<code>reproduce/program/r/</code> … R の一式。SDTM 作成から図表まで',
        '<code>reproduce/scripts/</code> … 索引・ReportingEvent・define.xml を作る Python',
        '<code>reproduce/docs/</code> … 仕様と、プログラムが読む宣言・受入基準',
        '<code>reproduce/input/</code> … 受領データと外部データ',
        '<code>reproduce/renv.lock</code> … R のパッケージの版',
    ]))
    b.append('<p>SAS の一式は入れていません。研究責任医師の環境に SAS が無く、'
             '渡しても動かせないためです。二重に作った事実は'
             '<a href="double-coding-report.html">二重作成の突合</a>が示します。</p>')
    return NL.join(b)


# --- SDRG ------------------------------------------------------------------------

def sdrg(t):
    ds = rows('sdtm_datasets.csv')
    vm = rows('variable-map.csv')
    cnt = {}
    for r in vm:
        if r['layer'] == 'sdtm':
            cnt[r['dataset']] = cnt.get(r['dataset'], 0) + 1
    b = []
    b.append('<h2>1. Introduction</h2>')
    b.append('<p>受領した標準データを読むための案内です。PHUSE の Study Data '
             'Reviewer’s Guide の様式に合わせて4節で書いています。この文書は生成物で、'
             '正本は <code>data/sdtm/define.xml</code>（表示用は'
             '<a href="define_sdtm.html">SDTM の define</a>）と'
             '<a href="sdtm-spec.html">SDTM 作成仕様</a>です。</p>')
    b.append(sec_protocol(t))
    b.append('<h2>3. Subject Data Description</h2>')
    b.append('<p>ドメインは %d 本です。試験の計画を表す Trial Design'
             '（TA・TE・TI・TS・TV）を含みます。</p>' % len(ds))
    b.append(ul(['<code>%s</code>（%s）%s'
                 % (esc(r['dataset']), esc(r['label']),
                    ' … 変数 %d' % cnt[r['dataset']] if r['dataset'] in cnt else '')
                 for r in ds]))
    b.append('<p>受領データを SDTM へ写す規則は'
             '<a href="sdtm-spec.html">SDTM 作成仕様</a>、'
             '症例報告書の入力欄との対応は'
             '<a href="../traceability.html">トレーサビリティ索引</a>が持ちます。</p>')
    b.append(sec_conformance(4))
    return NL.join(b)


# --- 総括報告書の原稿 ------------------------------------------------------------

def csr_parts():
    ents = entries()
    dev = [e for e in ents if e.get('区分') == '逸脱']
    post = [e for e in ents if e.get('区分') == '補完' and e.get('決め方') == '固定データ']
    pre = [e for e in ents if e.get('区分') == '補完' and e.get('決め方') == '文書のみ']
    b = []
    b.append('<p class="note">総括報告書の原稿です。ICH E3 は §9.8.3 を '
             'Changes in the Planned Analyses、§16.1.9 を統計手法の文書としています。'
             '本文は<a href="data-handling-decisions.html">データ取り扱い決定記録</a>の'
             '各エントリの先頭2段落を機械で並べた生成物で、そのまま提出する文章では'
             'ありません。エントリによっては先頭段落が決定ではなく解こうとした問題を'
             '述べているので、統計解析責任者が1件ずつ読んで書き直してください。'
             '文言の正本は台帳にあります。</p>')

    b.append('<h2>§9.8.3 Changes in the Planned Analyses</h2>')
    b.append('<h3>統計解析計画書の条文と実装が違う事項</h3>')
    b.append('<p>%d 件あります。</p>' % len(dev))
    for e in dev:
        b.append('<h4>%s</h4>' % esc(e['name']))
        b.append('<p>%s</p>' % esc(lead(e, 2)))
    b.append('<h3>固定データを見てから決めた事項</h3>')
    b.append('<p>統計解析計画書が答えを持たず、観測した件数・分布・欠測を見て決めた'
             'ものが %d 件あります。事後の判断にあたるため、確認的な結論としては'
             '読めません。</p>' % len(post))
    for e in post:
        b.append('<h4>%s</h4>' % esc(e['name']))
        b.append('<p>%s</p>' % esc(lead(e)))

    b.append('<h2>§16.1.9 統計手法の文書</h2>')
    b.append('<p>統計解析計画書が答えを持たず、一次文書と症例報告書の構造だけで'
             '決まった事項が %d 件あります。方法の選択にあたるもので、'
             '結果の読み方を変えるものではありません。</p>' % len(pre))
    for e in pre:
        b.append('<h4>%s</h4>' % esc(e['name']))
        b.append('<p>%s</p>' % esc(lead(e)))
    b.append('<p>統計手法と結果の記述そのものは'
             '<a href="statistical-methods-and-results.html">統計手法と結果</a>、'
             '結果を読むときの限界は納品パッケージの'
             '<a href="../README.html">最初のページ</a>にあります。</p>')
    return NL.join(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--define', help='ADaM の define.xml。データセットのラベルを引く')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    t = trial()
    labels = define_labels(a.define)

    made = []
    for name, title, sub, body in (
        ('analysis-data-reviewers-guide.html', '解析データの案内',
         'PHUSE Analysis Data Reviewer’s Guide の様式による7節。生成物です',
         adrg(t, labels)),
        ('study-data-reviewers-guide.html', '受領データの案内',
         'PHUSE Study Data Reviewer’s Guide の様式による4節。生成物です',
         sdrg(t)),
        ('csr-deviations.html', '総括報告書の原稿（変更と統計手法）', '', csr_parts()),
    ):
        p = os.path.join(a.out_dir, name)
        open(p, 'w', encoding='utf-8', newline=NL).write(page(title, sub, body))
        made.append((name, os.path.getsize(p)))
    if not a.quiet:
        ents = entries()
        n = {k: sum(1 for e in ents if e.get('区分') == k)
             for k in ('逸脱', '補完', '解消')}
        print('  案内3件を作った（台帳 %d 件。逸脱 %d・補完 %d・解消 %d、'
              'データセットのラベル %d 件）'
              % (len(ents), n['逸脱'], n['補完'], n['解消'], len(labels)))
        for name, size in made:
            print('    %s %d バイト' % (name, size))


if __name__ == '__main__':
    main()
