# run-sdtm-validation.py
#
# SDTM の適合性検証を一続きで回す。
#   1. 宣言と実データの照合（値水準と CodeList の値）
#   2. define.xml の更新と HTML 化
#   3. 検証に掛ける Dataset-JSON を整える（BOM 除去・読み取り確認・define.xml の配置）
#   4. CDISC CORE による検証
#
# 2026-09-05 に SAS を要する段階を無くし（段C）、define.xml の生成を実装系統から切り離した
# （段F。docs/records/sas-to-r-package-migration-20260905.md）。生成が読むのは受領
# define.xml と docs/metadata/ の宣言だけで、Dataset-JSON は読まない。段階1は宣言が実データと
# 合っているかを見るだけで、何も書き出さない。SAS 系の Dataset-JSON は二重コーディングの
# 突合が使い、適合性検証は納品するものだけを見る。
#
# 前提：R 系の Dataset-JSON が Box の datasets/r/sdtm/json に出来ていること
#       （program/r/<試験ID>_CSVtoSDTM.R を先に実行する）
#       CDISC CORE が %USERPROFILE%\opt\cdisc-core\core に入っていること
#       方法論の正本は akiko-office docs/methods/sdtm-conformance-validation.md
#
# 使い方：python scripts/run-sdtm-validation.py
#         python scripts/run-sdtm-validation.py --log-dir <dir>   ... ログの置き場を変える
#         python scripts/run-sdtm-validation.py --json-dir <dir>  ... 検証する Dataset-JSON
#                                                                    （既定は R 系）
import argparse
import csv
import glob
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runcommon  # noqa: E402

BOM = b'\xef\xbb\xbf'


def call(argv, what, tail=None, cwd=None):
    """外部プロセスを1本回し、標準出力の末尾だけを画面へ出す。

    外部プロセスの失敗は例外にならない。出力を末尾数行に絞っているため、見ないと
    失敗した旨まで画面から消える。終了コードで止める。2026-08-25 の docs 階層化で
    define.xml の生成が参照する CSV のパスが取り残され、それ以降 define.xml が
    更新されないまま検証だけが進んでいた（2026-09-05 に発見）。
    """
    p = subprocess.run(argv, cwd=cwd, check=False, stdout=subprocess.PIPE,
                       text=True, encoding='utf-8', errors='replace')
    lines = (p.stdout or '').splitlines()
    for ln in (lines[-tail:] if tail else lines):
        print(ln)
    if p.returncode != 0:
        raise SystemExit('%s が失敗しました（終了コード %d）' % (what, p.returncode))


def main():
    runcommon.setup_console()
    ap = argparse.ArgumentParser()
    ap.add_argument('--log-dir')
    ap.add_argument('--json-dir')
    args = ap.parse_args()

    repo = runcommon.REPO
    box = runcommon.trial_root()
    core = os.path.join(os.environ.get('USERPROFILE', ''),
                        'opt', 'cdisc-core', 'core', 'core.exe')
    stamp = time.strftime('%Y%m%d')
    skills = os.path.join(os.environ.get('USERPROFILE', ''), '.claude', 'skills',
                          'cdisc-define-xml', 'scripts')

    # CORE の結果の置き場。既定は invoke_sas と同じ試験フォルダの log で、--root で出力先を
    # 隔離したときもログだけ本番へ落ちないように trial_root() を通す（runcommon.py）。
    log_dir = args.log_dir or os.path.join(box, 'log')
    os.makedirs(log_dir, exist_ok=True)

    # 検証に掛ける Dataset-JSON。納品するのは R 系なので既定はそちら。
    # 何を検証したのかが結果から見えるように、必ず在処と更新日時を出す。
    json_dir = args.json_dir or os.path.join(box, 'datasets', 'r', 'sdtm', 'json')
    if not os.path.isdir(json_dir):
        raise SystemExit('Dataset-JSON がありません: %s' % json_dir)
    mtime = time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(json_dir)))
    print('検証する Dataset-JSON: %s（%s）' % (json_dir, mtime))

    if not os.path.isfile(core):
        raise SystemExit('見つかりません: %s' % core)

    print('1. 宣言と実データの照合')
    # define.xml の生成が読む宣言（値水準・CodeList の値）が実データと合っているかを見る。
    # 合わなければここで止める。宣言が実装の事実を言い直してよいのは、突き合わせる検査を
    # 付けられるときだけである。
    call([sys.executable, os.path.join(repo, 'scripts', 'check-sdtm-declarations.py'),
          '--json-dir', json_dir], '宣言と実データの照合', tail=4)

    print('2. define.xml の更新')
    # update-define-xml.py は SDTM IG の Role とラベルの一覧を読む。ドメインが増えたときに
    # 追随させるため毎回作り直す。引くのはスキル cdisc-define-xml のスクリプトで、
    # 出どころは CDISC CORE のキャッシュ（元は CDISC Library）。対象ドメインは
    # docs/metadata/sdtm_datasets.csv（データセットの正本）から採る。
    ig_meta = os.path.join(skills, 'export-sdtm-metadata.py')
    if not os.path.isfile(ig_meta):
        raise SystemExit('スキル cdisc-define-xml が見つかりません: %s' % ig_meta)
    call([sys.executable, ig_meta,
          '--out', os.path.join(repo, 'docs', 'metadata', 'external',
                                'sdtmig-3-2-variable-roles.csv'),
          '--domains-from', os.path.join(repo, 'docs', 'metadata', 'sdtm_datasets.csv')],
         'SDTM IG の変数メタデータの書き出し', tail=2)
    # DOMAIN の CodeList に付ける NCI の C コードは CDISC CT が正本。同じスキルの
    # export-ct-codelist.py で写しを作り直す（CORE-000929 が Alias を見る）。
    ct_meta = os.path.join(skills, 'export-ct-codelist.py')
    if not os.path.isfile(ct_meta):
        raise SystemExit('スキル cdisc-define-xml が見つかりません: %s' % ct_meta)
    call([sys.executable, ct_meta,
          '--out', os.path.join(repo, 'docs', 'metadata', 'external', 'ct-domain-ccode.csv'),
          '--codelist', 'C66734'], 'CT のコードリストの書き出し', tail=1)
    call([sys.executable, os.path.join(repo, 'scripts', 'update-define-xml.py')],
         'define.xml の更新', tail=5)

    print('   define.xml の HTML 化')
    # 変換の正本は scripts/build-define-html.R。ここで自前に書くと同じ生成が2箇所になる。
    # XSLT は R が持つ（Python の標準ライブラリに無い。pipeline/analysis-pipeline-plan.md「実行できる形を Python と R に限る」）
    call([runcommon.find_rscript(),
          os.path.join(repo, 'scripts', 'build-define-html.R'), '--layer=sdtm'],
         'define.html の生成', cwd=repo)

    print('3. 検証に掛ける Dataset-JSON を整える')
    # SAS の encoding='utf-8' は BOM を書き出すが、CORE の JSON パーサは BOM 付きを読めない。
    # R 系は BOM を書かないので通常は0件になる。SAS 系を --json-dir で指したときに効く。
    n = 0
    for path in sorted(glob.glob(os.path.join(json_dir, '*.json'))):
        with open(path, 'rb') as f:
            data = f.read()
        if data.startswith(BOM):
            with open(path, 'wb') as f:
                f.write(data[len(BOM):])
            n += 1
    print('   BOM を除去: %d ファイル' % n)

    # CORE の一部のルール（DOMAIN コードの照合、define と IG の role 照合）は
    # -dxp とは別に、データセットと同じフォルダの define.xml を直接開く。
    # 置かないと "No such file or directory" で 32 件のルールが EXECUTION ERROR になる。
    shutil.copyfile(os.path.join(box, 'datasets', 'define', 'sdtm', 'define.xml'),
                    os.path.join(json_dir, 'define.xml'))
    print('   define.xml をデータフォルダへ配置')

    # Box Drive は書き込み直後のファイルを別プロセスから読めないことがある
    # （CORE が "Your data file could not be read" で落ちる）。読めるまで待つ。
    files = sorted(glob.glob(os.path.join(json_dir, '*.json')))
    for attempt in range(1, 11):
        ng = 0
        for path in files:
            try:
                with open(path, encoding='utf-8') as f:
                    json.load(f)
            except (OSError, ValueError):
                ng += 1
        if ng == 0:
            print('   %d ファイルの読み取りを確認' % len(files))
            break
        time.sleep(3)
        if attempt == 10:
            raise SystemExit('Dataset-JSON を読み取れません（%d ファイル）' % ng)

    print('4. CDISC CORE による検証')
    # define.xml は渡さない。CORE 同梱の odmlib が Define-XML 2.0 の ItemGroupDef/@def:Class を
    # 扱えず読み込み時に落ちるため（2.1 は Class が子要素）。変数メタデータは Dataset-JSON が持つ。
    out = os.path.join(log_dir, '%s-sdtm-validation' % stamp)
    t0 = time.monotonic()
    # CORE は resources\schema\dataset.schema.json を相対パスで開くため、
    # カレントディレクトリを core.exe の場所にしないと Dataset-JSON を読めない。
    call([core, 'validate', '-s', 'sdtmig', '-v', '3-2', '-d', json_dir,
          '-ct', 'sdtmct-2026-03-27', '-of', 'JSON', '-o', out, '-p', 'disabled'],
         'CDISC CORE による検証', tail=3, cwd=os.path.dirname(core))
    print('   所要時間 %s 秒' % round(time.monotonic() - t0, 1))

    with open(out + '.json', encoding='utf-8') as f:
        j = json.load(f)
    return report(j, repo)


def report(j, repo):
    print('')
    print('ルール実行状況')
    counts = {}
    for r in j['Rules_Report']:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    for name, cnt in sorted(counts.items(), key=lambda kv: -kv[1]):
        print('  %-16s %d' % (name, cnt))

    # 仕分けの正本は docs/metadata/core-issue-disposition.csv。既知として残すと決めたルールを別枠に
    # 出し、未仕分けの指摘が件数の多い既知に埋もれないようにする。CORE 自体は素のまま回して
    # 全件を JSON に残す。--exclude-rules で除外すると、何を外したかが JSON から見えなくなり、
    # データの設計が変わって指摘の性質が変わっても気づけない。
    # EXECUTION ERROR のルールも Issue_Summary に各1件として現れる（ルールが実行できな
    # かった旨の報告。指摘ではない）。status で分けないと指摘の件数に混ざる。
    rmsg = {r['core_id']: r.get('message') for r in j['Rules_Report']}
    stat = {r['core_id']: r.get('status') for r in j['Rules_Report']}
    # 仕分け表が読めないまま進むと、既知の指摘が0件と表示されて未仕分けの山に埋もれる。
    # 2026-08-25 の docs 階層化でパスが取り残され、2026-08-29 まで気づけなかったため止める。
    disp_path = os.path.join(repo, 'docs', 'metadata', 'core-issue-disposition.csv')
    if not os.path.isfile(disp_path):
        print('仕分け表が見つかりません: %s' % disp_path)
        return 2
    disp = {}
    with open(disp_path, encoding='utf-8-sig', newline='') as f:
        rdr = csv.DictReader(f)
        if 'ds' not in (rdr.fieldnames or []):
            print('仕分け表に ds 列がありません: %s' % disp_path)
            print('  許容の対象データセットを書く列です。; 区切りで並べ、全ドメインに'
                  '及ぶときだけ ALL と書きます。')
            print('  列が無いまま通すと、あるドメインで許容した指摘が別ドメインの'
                  '本当の欠陥まで飲み込みます。')
            return 2
        for row in rdr:
            disp[row['core_id']] = row

    # 許容は core_id だけで結ばない。同じルールでも別のドメインの指摘は別に審査する。
    # ルール単位で許容すると、あるドメインの形式的な指摘を known にした後、次のカットで
    # 別ドメインに出た本当の欠陥が同じルールに当たって全件既知になる。
    def allowed(core_id, ds, want):
        r = disp.get(core_id)
        if not r or (r.get('disposition') or '').strip() != want:
            return False
        tgt = {x.strip().upper()
               for x in (r.get('ds') or '').replace(';', ',').split(',') if x.strip()}
        # 対象を書いていない行は全件許容にしない。書き忘れを許容と読まない
        return bool(tgt) and ('ALL' in tgt or ds in tgt)

    rows = []
    for it in j['Issue_Summary']:
        core_id = it['core_id']
        ds = (it.get('dataset') or '').upper()
        key = (core_id, ds)
        g = next((r for r in rows if (r['core_id'], r['ds']) == key), None)
        if g is None:
            g = {'core_id': core_id, 'ds': ds, 'issues': 0, 'status': stat.get(core_id)}
            rows.append(g)
        g['issues'] += it.get('issues') or 0
    for r in rows:
        if r['status'] == 'EXECUTION ERROR':
            r['disp'] = 'execerr-ok' if allowed(r['core_id'], r['ds'], 'execerror-ok') else 'execerr'
        else:
            r['disp'] = 'known' if allowed(r['core_id'], r['ds'], 'known') else 'open'

    execerr = [r for r in rows if r['disp'] == 'execerr']
    execok = [r for r in rows if r['disp'] == 'execerr-ok']
    known = sorted([r for r in rows if r['disp'] == 'known'], key=lambda r: -r['issues'])
    rest = sorted([r for r in rows if r['disp'] == 'open'], key=lambda r: -r['issues'])

    print('')
    print('既知として残すと決めた指摘 : %d 件（ルール×ドメイン）/ %s 件'
          % (len(known), format(sum(r['issues'] for r in known), ',d')))
    for k in known:
        print('  %6d 件  %s  [%s]  %s'
              % (k['issues'], k['core_id'], k['ds'], disp[k['core_id']]['note']))
    print('')
    print('未仕分け : %d 件（ルール×ドメイン）/ %s 件（件数順に15まで）'
          % (len(rest), format(sum(r['issues'] for r in rest), ',d')))
    for r in rest[:15]:
        print('  %6d 件  %s  [%s]  %s'
              % (r['issues'], r['core_id'], r['ds'], rmsg.get(r['core_id'])))
    if execok:
        print('')
        print('実行できなかったが承認済みのルール : %d 件' % len(execok))
        for e in execok:
            print('  %s  [%s]  %s'
                  % (e['core_id'], e['ds'], disp[e['core_id']]['note']))
    if execerr:
        print('')
        print('ルールが実行できなかったもの（未承認） : %d 件' % len(execerr))
        for e in execerr:
            print('  %s  [%s]  %s' % (e['core_id'], e['ds'], rmsg.get(e['core_id'])))

    print('')
    if rest or execerr:
        print('未仕分け %d 件・未承認の実行失敗 %d 件。工程の出口条件を満たしません。'
              % (len(rest), len(execerr)))
        print('  残すと決めたものは core-issue-disposition.csv へ、'
              '対象データセットを ds 列に書いて1行ずつ足します。')
        return 1
    print('未仕分け 0 件・未承認の実行失敗 0 件。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
