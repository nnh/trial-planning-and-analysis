# check-visual-regression.py
#
# 図表を実際に描画して、基準（前回合意した見た目）と突き合わせる。
#
# 構造の検査は「ファイルがある」「リンクが切れていない」「両系統のセルが一致する」までしか
# 見ない。2026-08-29 に、それらをすべて通ったまま人の目で3件の描画不良が見つかった
# （時点表が89行、図の信頼区間が表と食い違う、Excel の生存曲線が系列0本）。見た目そのものを
# 突き合わせる検査を1つ置く（docs/validation/records/codex-review-2-ledger.md の C2-037）。
#
# 全図表を撮ると、体裁を1か所直すたびに88件が差分になって読めなくなる。対象は主要図表と
# 表示型ごとの代表例に限る。どれが代表かは docs/metadata/tlf-index.csv を表示型で畳んで
# 決めるので、ここに図表名を書かない。図は描画の誤りが出やすいので全件を見る。
#
# 基準は Box の output/qc/visual-baseline/<系統>-<言語>/ に置く。図表そのものと同じ
# 成果物なのでリポジトリには入れない。体裁を意図して変えたときは --update で取り直す。
#
# 対象は納品する4組（r-ja・r-en・sas-ja・sas-en）を既定にする。既定が R 系の日本語版
# だけだったため、英語版にだけ出る折り返しや欠落、SAS 系の描画不良が検査を通っていた
# （C3-116）。SAS 系の ARD から描く rsas は図表そのものを書かないので対象に含めない。
#
# 使い方
#   python scripts/check-visual-regression.py             ... 4組すべてを基準と突き合わせる
#   python scripts/check-visual-regression.py --update    ... 基準を取り直す
#   python scripts/check-visual-regression.py --lang en --system sas
#   python scripts/check-visual-regression.py --baseline <dir>  ... 基準の親を別の場所にする
#   python scripts/check-visual-regression.py --allow-skip ... 材料が無ければ検査せず終える
#
# 要 playwright（`pip install playwright && playwright install chromium`）。playwright か
# Box が無い端末では、何が無くて何を検査しなかったかを述べて非0で終える。材料が無いまま
# 0 を返すと、1件も撮らずに成果物の検査の段階が通る（C3-124）。診断のために飛ばすときは --allow-skip。
# 基準画像が無いときも通常の実行では非0で終える。比較も承認も経ていない成果物がそのまま
# 基準として固定されるのを避けるため、基準を作るのは --update だけにする（C3-118）。
import sys, os, csv, zlib, struct, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 描画の窓は固定する。幅が変わると折り返しが変わり、中身が同じでも差分になる
VIEWPORT = {'width': 1200, 'height': 900}
# 画素の差。反射防止のかかった書体は端で1階調ずれることがあるので、少しだけ許す
CHANNEL_TOL = 8


def targets():
    """撮る図表。表示型ごとの先頭1件、図の全件、そして名指しした図表。

    期待値はここに書かず、宣言（docs/metadata/tlf-index.csv）を畳んで得る。表示型が
    増えれば代表も自動で増える。

    表示型の先頭1件だけでは、同じ表示型の中で作りの違う図表が網から外れる。実際に
    2026-08-30 の対応で、地固め療法をコース別へ分けた表 5.4.7.4、列を2つ足した
    表 5.4.7.6、行を1つ足した表 5.4.2.1、判定の脚注を入れた表 5.4.1 のいずれもが
    代表に選ばれず、脚注が印のまま印字されていた欠陥（C2-214）は目視で初めて
    分かった。宣言の visual 列に印を付けた図表も撮る（2026-08-31。C2-218）。
    """
    p = os.path.join(REPO, 'docs', 'metadata', 'tlf-index.csv')
    with open(p, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: int(r['seq']))
    out, seen = [], set()
    for r in rows:
        if r['display'] not in seen:
            seen.add(r['display'])
            out.append(r['lblid'])
    for r in rows:
        if r['display'].startswith('fig_') and r['lblid'] not in out:
            out.append(r['lblid'])
    for r in rows:
        if (r.get('visual') or '').strip().upper() == 'Y' and r['lblid'] not in out:
            out.append(r['lblid'])
    return out


# PNG の色の種別ごとの画素あたりバイト数（深さ8のとき）。Playwright は透過の要らない
# 画面を種別2（RGB）で、要る画面を種別6（RGBA）で書き出す
PNG_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}


def png_pixels(b):
    """PNG を画素の列へ開く。幅・高さ・画素あたりバイト数・画素列を返す。

    画素の比較のために外部の画像ライブラリを入れたくない（Python は標準ライブラリだけで
    動かす方針）ので、zlib と struct で足りる範囲に留める。深さ8・非インタレース・
    パレット以外という、画面の撮像で実際に出てくる形だけを扱う。
    """
    if b[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('PNG ではない')
    i, idat, hdr = 8, [], None
    while i < len(b):
        n, kind = struct.unpack('>I4s', b[i:i + 8])
        body = b[i + 8:i + 8 + n]
        if kind == b'IHDR':
            hdr = struct.unpack('>IIBBBBB', body)
        elif kind == b'IDAT':
            idat.append(body)
        elif kind == b'IEND':
            break
        i += 12 + n
    w, h, depth, color, _, _, interlace = hdr
    if depth != 8 or interlace != 0 or color not in PNG_CHANNELS:
        raise ValueError(f'扱えない PNG（深さ{depth} 種別{color} インタレース{interlace}）')
    raw = zlib.decompress(b''.join(idat))
    bpp = PNG_CHANNELS[color]
    stride = w * bpp
    out = bytearray(h * stride)
    prev = bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            c = prev[x - bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x] + a) & 0xFF
            elif f == 2:
                line[x] = (line[x] + prev[x]) & 0xFF
            elif f == 3:
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 0xFF
            elif f == 4:
                p = a + prev[x] - c
                pa, pb, pc = abs(p - a), abs(p - prev[x]), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc
                                      else prev[x] if pb <= pc else c)) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return w, h, bpp, bytes(out)


def diff_ratio(a, b):
    """2枚の PNG の、食い違う画素の割合。大きさが違えば 1.0（全面差分）とみなす。

    同じ描画からは同じバイト列が出るので、まず丸ごと比べて、違うときだけ開く。
    画素の突き合わせは Python の繰り返しで行うため、開くのは差があるときに限りたい。
    """
    if a == b:
        return 0.0, '同一'
    wa, ha, ca, pa = png_pixels(a)
    wb, hb, cb, pb = png_pixels(b)
    if (wa, ha) != (wb, hb):
        return 1.0, f'大きさが違う（基準 {wb}x{hb} / 今回 {wa}x{ha}）'
    if ca != cb:
        return 1.0, f'色の持ち方が違う（基準 {cb}バイト / 今回 {ca}バイト）'
    # 透過の層は見ない。色の3層（灰色1層のときは1層）だけを比べる
    look = min(ca, 3)
    n = 0
    for i in range(0, len(pa), ca):
        for j in range(look):
            if abs(pa[i + j] - pb[i + j]) > CHANNEL_TOL:
                n += 1
                break
    return n / (wa * ha), f'食い違う画素 {n} / {wa * ha}'


def drop_actual(base, name):
    """前の回が残した <図表>.actual.png を消す。

    食い違ったときだけ書かれるファイルなので、食い違いが解けた回に消さないと、基準の
    置き場を見ただけでは、いまどれが食い違っているかが分からなくなる（2026-09-01 に
    1時間前の実行が書いた3件が残っていた）。消すのは食い違いが1つも無かった図表と、
    --update で基準を取り直した図表に限る。
    """
    p = os.path.join(base, name + '.actual.png')
    if os.path.exists(p):
        os.remove(p)
        return True
    return False


def run_one(pg, tlf, base, names, tol, update):
    """1組（系統×言語）を撮って基準と突き合わせる。食い違いの一覧と件数を返す。

    材料が無い側を素通りさせない。図表 HTML が無い、基準画像が無い、基準画像を開けないは
    いずれも食い違いとして数える。基準を作るのは --update のときだけで、通常の実行では
    作らない（C3-118・C3-119）。
    """
    err, miss, n_new, n_ok = [], [], 0, 0
    for name in names:
        html = os.path.join(tlf, name + '.html')
        if not os.path.exists(html):
            err.append(f'{name}: 図表 HTML が無い')
            continue
        pg.goto('file://' + html.replace(os.sep, '/'))
        pg.wait_for_timeout(400)
        shot = pg.screenshot(full_page=True)
        text = pg.inner_text('body')

        png, txt = os.path.join(base, name + '.png'), os.path.join(base, name + '.txt')
        if update:
            # 何を上書きしたかをログに残す。取り直しの回に、前の基準との差がどれだけ
            # あったかが後から読める（差を見ずに固定した回と区別が付く）
            if os.path.exists(png):
                try:
                    r, how = diff_ratio(shot, open(png, 'rb').read())
                    print(f'  基準を取り直す  {name}  差 {r:.4%}（{how}）')
                except ValueError as e:
                    print(f'  基準を取り直す  {name}  前の基準を開けない（{e}）')
            else:
                print(f'  基準を作る      {name}')
            open(png, 'wb').write(shot)
            open(txt, 'w', encoding='utf-8').write(text)
            # 取り直した基準は今回の描画そのものなので、前の回の .actual.png は用が無い
            drop_actual(base, name)
            n_new += 1
            continue
        if not os.path.exists(png):
            miss.append(name)
            continue

        # 題名・軸ラベル・セルの文字は画像より先に見る。文字が変わっていれば
        # 画素の差の理由がそこにあると分かる（OCR を入れずに同じことができる）
        old = open(txt, encoding='utf-8').read() if os.path.exists(txt) else ''
        bad = False
        if old and old != text:
            err.append(f'{name}: 画面の文字が基準と違う')
            bad = True
        try:
            r, how = diff_ratio(shot, open(png, 'rb').read())
        except ValueError as e:
            # 開けない基準は「差が無い」ではない。破損や形式変更を合格にしないため
            # 警告ではなく食い違いに入れる（C3-119）
            err.append(f'{name}: 画像を比べられない（{e}）')
            continue
        if r > tol:
            err.append(f'{name}: 見た目が基準と違う {r:.4%}（{how}）')
            bad = True
        if bad:
            open(os.path.join(base, name + '.actual.png'), 'wb').write(shot)
        else:
            drop_actual(base, name)
            n_ok += 1
    if miss:
        head = '・'.join(miss[:5]) + ('…' if len(miss) > 5 else '')
        err.append(f'基準画像が無い {len(miss)} 件（{head}）。'
                   '成果物を目で見てから --update で取る')
    return err, n_ok, n_new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lang', default='both', choices=['ja', 'en', 'both'])
    ap.add_argument('--system', default='both', choices=['r', 'sas', 'both'])
    ap.add_argument('--tol', type=float, default=0.002, help='許す画素差の割合')
    ap.add_argument('--update', action='store_true', help='基準を取り直す')
    ap.add_argument('--baseline', help='基準の親（既定は Box の output/qc/visual-baseline）')
    ap.add_argument('--allow-skip', action='store_true',
                    help='playwright や Box が無いとき、検査せず 0 で終える（診断用）')
    a = ap.parse_args()

    # 材料が無いまま 0 を返すと、1件も撮らずに成果物の検査の段階が通る（C3-124）。何が無いかを述べて
    # 非0で終え、飛ばすのは診断のために --allow-skip を付けたときだけにする
    lack = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        lack.append('playwright が入っていない'
                    '（pip install playwright && playwright install chromium）')
    box = boxpath.trial_dir(required=False)
    if not box:
        lack.append('Box の試験フォルダが見つからない（図表も基準もその下にある）')
    if lack:
        for x in lack:
            print('材料が無い:', x)
        if a.allow_skip:
            print('--allow-skip のため視覚回帰を1件も実施せずに終える')
            return 0
        print('視覚回帰を1件も実施していない。診断のために飛ばすなら --allow-skip を付ける')
        return 1

    langs = ['ja', 'en'] if a.lang == 'both' else [a.lang]
    systems = ['r', 'sas'] if a.system == 'both' else [a.system]
    root = a.baseline or os.path.join(box, 'output', 'qc', 'visual-baseline')
    names = targets()
    err = []

    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport=VIEWPORT, device_scale_factor=1)
        for system in systems:
            for lang in langs:
                tag = f'{system}-{lang}'
                tlf = os.path.join(box, 'output', 'tlf', tag)
                base = os.path.join(root, tag)
                if not os.path.isdir(tlf):
                    err.append(f'{tag}: 図表が無い（{tlf}）。先に図表を作る')
                    continue
                if a.update:
                    os.makedirs(base, exist_ok=True)
                elif not os.path.isdir(base):
                    err.append(f'{tag}: 基準の置き場が無い（{base}）。'
                               '成果物を目で見てから --update で取る')
                    continue
                print(f'{tlf} の {len(names)} 件を見る（基準 {base}）')
                e, n_ok, n_new = run_one(pg, tlf, base, names, a.tol, a.update)
                print(f'  {tag}: 一致 {n_ok} / 新規 {n_new} / 食い違い {len(e)}')
                err += [f'{tag} {x}' for x in e]
        br.close()

    for e in err:
        print('ERROR:', e)
    print(f'見た組 {len(systems) * len(langs)} / 食い違い {len(err)} 件')
    if err:
        print('意図した変更なら --update で基準を取り直す。'
              '取り直す前に、差分が意図どおりかを目で見ること。')
    return 1 if err else 0


if __name__ == '__main__':
    sys.exit(main())
