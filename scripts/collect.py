"""
Disney Wait Time Collector v2
------------------------------
queue-times.com の無料API から東京ディズニーランド＆シーの
主要アトラクション待ち時間を取得し、Google Sheets に記録する。

シート構成:
  📊 ダッシュボード  … サマリー + 現在の待ち時間一覧 + グラフ（自動更新）
  [アトラ名]         … アトラクションごとの時系列ログ（主要アトラ分）

Park IDs:
  274 = Tokyo Disneyland (TDL)
  275 = Tokyo DisneySea  (TDS)
"""

import os, json, time, datetime, requests, gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ══════════════════════════════════════════════════════
# 主要アトラクション定義（queue-times.com の ride["name"] と一致）
# ══════════════════════════════════════════════════════
TDL_KEY_RIDES = [
    "Space Mountain",
    "Big Thunder Mountain",
    "Splash Mountain",
    "Haunted Mansion",
    "Pirates of the Caribbean",
    "Pooh's Hunny Hunt",
    "Beauty and the Beast: Enchanted Tale",
    "Monsters, Inc. Ride & Go Seek!",
    "Baymax's Happy Ride",
    "Buzz Lightyear's Astro Blasters",
    "Star Tours: The Adventures Continue",
    "Peter Pan's Flight",
]

TDS_KEY_RIDES = [
    "Journey to the Center of the Earth",
    "Tower of Terror",
    "Indiana Jones Adventure: Temple of the Crystal Skull",
    "Raging Spirits",
    "Sindbad's Storybook Voyage",
    "20,000 Leagues Under the Sea",
    "Toy Story Mania!",
    "Turtle Talk",
    "Nemo & Friends SeaRider",
    "Soaring: Fantastic Flight",
    "Frozen Ever After",
    "Rapunzel's Lantern Festival",
]

PARKS = {"TDL": 274, "TDS": 275}

CROWD_ESTIMATE = [
    (10,  "〜15,000人"),
    (20,  "〜25,000人"),
    (35,  "〜35,000人"),
    (50,  "〜50,000人"),
    (70,  "〜60,000人"),
    (999, "〜70,000人"),
]

DASH_SHEET     = "📊 ダッシュボード"
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]


# ══════════════════════════════════════════════════════
# カラー定義
# ══════════════════════════════════════════════════════
def rgb(r, g, b):
    return {"red": r/255, "green": g/255, "blue": b/255}

COLOR_TDL_HEADER = rgb(30, 90, 180)
COLOR_TDS_HEADER = rgb(0, 130, 100)
COLOR_DASH_BG    = rgb(15, 25, 50)
COLOR_WHITE      = rgb(255, 255, 255)
COLOR_LIGHT_GRAY = rgb(240, 240, 248)
COLOR_GOLD       = rgb(255, 205, 30)
COLOR_BLUE_BAR   = rgb(30, 120, 255)

_req_buf: list = []   # batchUpdate リクエストを蓄積するバッファ


# ══════════════════════════════════════════════════════
# 認証
# ══════════════════════════════════════════════════════
def get_clients():
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets",
    ]
    creds      = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc         = gspread.authorize(creds)
    sheets_svc = build("sheets", "v4", credentials=creds)
    return gc, sheets_svc


# ══════════════════════════════════════════════════════
# API からデータ取得
# ══════════════════════════════════════════════════════
def fetch_park(park_id: int) -> dict:
    url = f"https://queue-times.com/parks/{park_id}/queue_times.json"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()

def flatten_rides(data: dict) -> dict:
    """{ ride_name: {is_open, wait_time, land} } を返す"""
    result = {}
    for land in data.get("lands", []):
        for ride in land.get("rides", []):
            result[ride["name"]] = {
                "is_open":   ride["is_open"],
                "wait_time": ride["wait_time"],
                "land":      land["name"],
            }
    for ride in data.get("rides", []):
        result[ride["name"]] = {
            "is_open":   ride["is_open"],
            "wait_time": ride["wait_time"],
            "land":      "—",
        }
    return result

def estimate_crowd(avg_wait: float) -> str:
    for threshold, label in CROWD_ESTIMATE:
        if avg_wait <= threshold:
            return label
    return "〜70,000人"


# ══════════════════════════════════════════════════════
# シート取得 or 作成
# ══════════════════════════════════════════════════════
def get_or_create_sheet(ss, title: str, rows=3000, cols=10) -> gspread.Worksheet:
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        return ss.add_worksheet(title=title, rows=rows, cols=cols)


# ══════════════════════════════════════════════════════
# Sheets API ヘルパー
# ══════════════════════════════════════════════════════
def _exec(svc, ss_id, reqs):
    """リクエストをバッファに積む（実行は _flush で一括）"""
    _req_buf.extend(reqs)

def _flush(svc, ss_id, chunk=150):
    """バッファのリクエストをまとめて送信"""
    global _req_buf
    if not _req_buf:
        return
    for i in range(0, len(_req_buf), chunk):
        svc.spreadsheets().batchUpdate(
            spreadsheetId=ss_id,
            body={"requests": _req_buf[i:i+chunk]}
        ).execute()
        if i + chunk < len(_req_buf):
            time.sleep(2)
    _req_buf = []

def _fmt(svc, ss_id, sid, r1, c1, r2, c2, bg=None, fg=None, bold=None, fs=None):
    fmt   = {}
    tf    = {}
    flds  = []
    if bg:
        fmt["backgroundColor"] = bg
        flds.append("backgroundColor")
    if fg:        tf["foregroundColor"] = fg
    if bold is not None: tf["bold"] = bold
    if fs:        tf["fontSize"] = fs
    if tf:
        fmt["textFormat"] = tf
        flds.append("textFormat")
    if not flds:
        return
    _exec(svc, ss_id, [{"repeatCell": {
        "range": {"sheetId": sid,
                  "startRowIndex": r1, "endRowIndex": r2,
                  "startColumnIndex": c1, "endColumnIndex": c2},
        "cell":  {"userEnteredFormat": fmt},
        "fields": "userEnteredFormat(" + ",".join(flds) + ")"
    }}])

def _merge(svc, ss_id, sid, r1, c1, r2, c2):
    _exec(svc, ss_id, [{"mergeCells": {
        "range": {"sheetId": sid,
                  "startRowIndex": r1, "endRowIndex": r2,
                  "startColumnIndex": c1, "endColumnIndex": c2},
        "mergeType": "MERGE_ALL"
    }}])

def _col_widths(svc, ss_id, sid, widths: list):
    reqs = []
    for i, w in enumerate(widths):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": i, "endIndex": i+1},
            "properties": {"pixelSize": w},
            "fields": "pixelSize"
        }})
    _exec(svc, ss_id, reqs)

def _row_height(svc, ss_id, sid, r1, r2, px):
    _exec(svc, ss_id, [{"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS",
                  "startIndex": r1, "endIndex": r2},
        "properties": {"pixelSize": px},
        "fields": "pixelSize"
    }}])

def _move_front(svc, ss_id, sid):
    _exec(svc, ss_id, [{"updateSheetProperties": {
        "properties": {"sheetId": sid, "index": 0},
        "fields": "index"
    }}])

def _delete_charts(svc, ss_id, sid):
    """シート上の既存チャートを全削除"""
    try:
        meta = svc.spreadsheets().get(
            spreadsheetId=ss_id,
            fields="sheets(properties(sheetId),charts(chartId))"
        ).execute()
        reqs = []
        for sh in meta.get("sheets", []):
            if sh["properties"]["sheetId"] == sid:
                for ch in sh.get("charts", []):
                    reqs.append({"deleteEmbeddedObject":
                                 {"objectId": ch["chartId"]}})
        if reqs:
            _exec(svc, ss_id, reqs)
    except Exception as e:
        print(f"  chart cleanup warn: {e}")

def _add_bar_chart(svc, ss_id, sid,
                   domain_r1, domain_r2,   # アトラ名の行範囲
                   series_r1, series_r2,   # 待ち時間の行範囲
                   col_domain, col_series,
                   anchor_row, anchor_col,
                   title="現在の待ち時間（分）"):
    _exec(svc, ss_id, [{"addChart": {"chart": {
        "spec": {
            "title": title,
            "titleTextFormat": {"bold": True, "fontSize": 13,
                                "foregroundColor": rgb(20,20,50)},
            "basicChart": {
                "chartType": "BAR",
                "legendPosition": "NO_LEGEND",
                "axis": [
                    {"position": "BOTTOM_AXIS", "title": "待ち時間（分）"},
                    {"position": "LEFT_AXIS",   "title": ""}
                ],
                "domains": [{"domain": {"sourceRange": {"sources": [{
                    "sheetId": sid,
                    "startRowIndex":    domain_r1,
                    "endRowIndex":      domain_r2,
                    "startColumnIndex": col_domain,
                    "endColumnIndex":   col_domain + 1,
                }]}}}],
                "series": [{"series": {"sourceRange": {"sources": [{
                    "sheetId": sid,
                    "startRowIndex":    series_r1,
                    "endRowIndex":      series_r2,
                    "startColumnIndex": col_series,
                    "endColumnIndex":   col_series + 1,
                }]}},
                    "targetAxis": "BOTTOM_AXIS",
                    "colorStyle": {"rgbColor": COLOR_BLUE_BAR}
                }]
            }
        },
        "position": {"overlayPosition": {
            "anchorCell": {"sheetId": sid,
                           "rowIndex": anchor_row, "columnIndex": anchor_col},
            "widthPixels":  680,
            "heightPixels": 480
        }}
    }}}])


def _add_line_chart(svc, ss_id, sid,
                    domain_col, series: list,  # [(col, color), ...]
                    max_row, anchor_row, anchor_col, title=""):
    """折れ線グラフを追加（series は (列インデックス, rgbColor) のリスト）"""
    src = lambda col: [{
        "sheetId": sid,
        "startRowIndex": 0, "endRowIndex": max_row,
        "startColumnIndex": col, "endColumnIndex": col + 1,
    }]
    _exec(svc, ss_id, [{"addChart": {"chart": {
        "spec": {
            "title": title,
            "titleTextFormat": {"bold": True, "fontSize": 13},
            "basicChart": {
                "chartType": "LINE",
                "legendPosition": "BOTTOM_LEGEND",
                "headerCount": 1,
                "axis": [
                    {"position": "BOTTOM_AXIS", "title": ""},
                    {"position": "LEFT_AXIS",   "title": "待ち時間（分）"},
                ],
                "domains": [{"domain": {"sourceRange": {"sources": src(domain_col)}}}],
                "series": [
                    {"series": {"sourceRange": {"sources": src(col)}},
                     "targetAxis": "LEFT_AXIS",
                     "colorStyle": {"rgbColor": color}}
                    for col, color in series
                ],
            }
        },
        "position": {"overlayPosition": {
            "anchorCell": {"sheetId": sid,
                           "rowIndex": anchor_row, "columnIndex": anchor_col},
            "widthPixels": 720, "heightPixels": 420,
        }}
    }}}])


# ══════════════════════════════════════════════════════
# サマリー（日次混雑記録）
# ══════════════════════════════════════════════════════
SUMMARY_SHEET   = "サマリー"
SUMMARY_HEADERS = [
    "日時(JST)",
    "TDL平均待ち(分)", "TDL推定入場者数", "TDL運営中",
    "TDS平均待ち(分)", "TDS推定入場者数", "TDS運営中",
]

def _sheet_has_charts(svc, ss_id, sid) -> bool:
    for attempt in range(3):
        try:
            meta = svc.spreadsheets().get(
                spreadsheetId=ss_id,
                fields="sheets(properties(sheetId),charts)"
            ).execute()
            for sh in meta.get("sheets", []):
                if sh["properties"]["sheetId"] == sid:
                    return bool(sh.get("charts"))
            return False
        except Exception as e:
            if attempt < 2:
                print(f"  _sheet_has_charts retry ({attempt+1}): {e}")
                time.sleep(5)
            else:
                print(f"  _sheet_has_charts failed, skip chart check: {e}")
                return True  # 失敗時はグラフ作成をスキップ

def write_summary(ss, svc, now_jst, summaries: dict):
    ws = get_or_create_sheet(ss, SUMMARY_SHEET, rows=5000, cols=8)
    first = ws.row_values(1)
    if first != SUMMARY_HEADERS:
        ws.update("A1:G1", [SUMMARY_HEADERS])
        _fmt(svc, ss.id, ws.id, 0, 0, 1, 7,
             bg=COLOR_DASH_BG, fg=COLOR_GOLD, bold=True, fs=10)
        _col_widths(svc, ss.id, ws.id, [150, 120, 120, 80, 120, 120, 80])
        _flush(svc, ss.id)

    if not _sheet_has_charts(svc, ss.id, ws.id):
        _add_line_chart(svc, ss.id, ws.id,
                        domain_col=0,
                        series=[(1, COLOR_TDL_HEADER), (4, COLOR_TDS_HEADER)],
                        max_row=5000,
                        anchor_row=0, anchor_col=8,
                        title="TDL / TDS 平均待ち時間の推移（分）")
        _flush(svc, ss.id)
        print("  サマリー: グラフを作成")

    tdl = summaries.get("TDL", {})
    tds = summaries.get("TDS", {})
    ws.append_row([
        now_jst.strftime("%Y-%m-%d %H:%M"),
        tdl.get("avg_wait", ""),  tdl.get("crowd", ""), tdl.get("open_count", ""),
        tds.get("avg_wait", ""),  tds.get("crowd", ""), tds.get("open_count", ""),
    ], value_input_option="USER_ENTERED")
    print(f"  サマリー: 1行追記（TDL {tdl.get('avg_wait','-')}分 / TDS {tds.get('avg_wait','-')}分）")


# ══════════════════════════════════════════════════════
# アトラクション個別タブ
# ══════════════════════════════════════════════════════
def write_attraction_tabs(ss, svc, now_jst, ride_data: dict):
    HEADERS = ["日時(JST)", "待ち時間(分)", "運営状態"]
    for name, info in ride_data.items():
        ws = get_or_create_sheet(ss, name, rows=3000, cols=5)
        first = ws.row_values(1)
        if first != HEADERS:
            ws.update("A1:C1", [HEADERS])
            color = COLOR_TDL_HEADER if info["park"] == "TDL" else COLOR_TDS_HEADER
            _fmt(svc, ss.id, ws.id, 0, 0, 1, 3,
                 bg=color, fg=COLOR_WHITE, bold=True, fs=11)
            _col_widths(svc, ss.id, ws.id, [160, 110, 100])
            _row_height(svc, ss.id, ws.id, 0, 1, 28)

        status = "運営中" if info["is_open"] else "休止中"
        wait   = info["wait_time"] if info["is_open"] else ""
        ws.append_row(
            [now_jst.strftime("%Y-%m-%d %H:%M"), wait, status],
            value_input_option="USER_ENTERED"
        )
    _flush(svc, ss.id)
    print(f"  個別タブ: {len(ride_data)} シート更新")


# ══════════════════════════════════════════════════════
# ダッシュボード
# ══════════════════════════════════════════════════════
def write_dashboard(ss, svc, now_jst, ride_data: dict, summaries: dict):
    ws = get_or_create_sheet(ss, DASH_SHEET, rows=200, cols=20)
    ws.clear()
    _delete_charts(svc, ss.id, ws.id)

    values = []   # 書き込む値（行ごと）
    row = 0       # 0-indexed

    # ── タイトル ─────────────────────────────────────
    ts = now_jst.strftime("%Y/%m/%d %H:%M")
    values.append([f"🏰 TDR 待ち時間ダッシュボード　最終更新: {ts} JST"])
    _row_height(svc, ss.id, ws.id, row, row+1, 36)
    row += 1
    values.append([])  # 空行
    row += 1

    # ── TDL / TDS サマリーカード ──────────────────────
    for park, s in summaries.items():
        park_name = "東京ディズニーランド" if park == "TDL" else "東京ディズニーシー"
        emoji     = "🏯" if park == "TDL" else "🌊"
        hdr_color = COLOR_TDL_HEADER if park == "TDL" else COLOR_TDS_HEADER

        values.append([f"{emoji} {park_name}（{park}）"])
        _row_height(svc, ss.id, ws.id, row, row+1, 30)
        row += 1

        values.append([
            "平均待ち",   f"{s['avg_wait']} 分",
            "最長待ち",   f"{s['max_wait']} 分  ／  {s['max_name']}",
            "推定入場者", s['crowd'],
            "運営中",     f"{s['open_count']} 本",
            "休止中",     f"{s['closed_count']} 本",
        ])
        _row_height(svc, ss.id, ws.id, row, row+1, 28)
        row += 1
        values.append([])
        row += 1

    # ── 待ち時間テーブル ──────────────────────────────
    values.append(["📋 現在の待ち時間一覧"])
    row += 1

    TBLH = ["パーク", "アトラクション名", "待ち時間(分)", "状態", "累計記録数"]
    values.append(TBLH)
    tbl_header_row = row
    row += 1

    tbl_data_start = row
    tdl_rows, tds_rows = [], []

    for name, info in ride_data.items():
        try:
            ride_ws  = ss.worksheet(name)
            # 実データ行 = row_count はシートの行上限なので値で取得
            all_vals = ride_ws.col_values(1)
            log_cnt  = max(0, len(all_vals) - 1)   # ヘッダー1行除く
        except Exception:
            log_cnt = 0

        status = "🟢 運営中" if info["is_open"] else "🔴 休止中"
        wait   = info["wait_time"] if info["is_open"] and info["wait_time"] > 0 else "—"
        entry  = [info["park"], name, wait, status, log_cnt]
        if info["park"] == "TDL":
            tdl_rows.append(entry)
        else:
            tds_rows.append(entry)

    # TDL → TDS の順に並べる
    ordered = tdl_rows + tds_rows
    for r in ordered:
        values.append(r)
    row += len(ordered)
    tbl_data_end = row

    # まとめて書き込み
    ws.update("A1", values, value_input_option="USER_ENTERED")

    # ── フォーマット適用 ──────────────────────────────
    cur = 0

    # タイトル
    _fmt(svc, ss.id, ws.id, cur, 0, cur+1, 10,
         bg=COLOR_DASH_BG, fg=COLOR_GOLD, bold=True, fs=15)
    _merge(svc, ss.id, ws.id, cur, 0, cur+1, 10)
    cur += 2  # タイトル + 空行

    # サマリーカード
    for park in summaries:
        hdr_color = COLOR_TDL_HEADER if park == "TDL" else COLOR_TDS_HEADER
        # パーク名行
        _fmt(svc, ss.id, ws.id, cur, 0, cur+1, 10,
             bg=hdr_color, fg=COLOR_WHITE, bold=True, fs=12)
        _merge(svc, ss.id, ws.id, cur, 0, cur+1, 10)
        cur += 1
        # 数値行（ラベル/値 交互）
        for c in range(0, 10, 2):
            _fmt(svc, ss.id, ws.id, cur, c, cur+1, c+1,
                 bg=COLOR_LIGHT_GRAY, bold=False, fs=10)
            _fmt(svc, ss.id, ws.id, cur, c+1, cur+1, c+2,
                 bg=COLOR_WHITE, bold=True, fs=11)
        cur += 2  # 数値行 + 空行

    # 「現在の待ち時間一覧」見出し
    _fmt(svc, ss.id, ws.id, cur, 0, cur+1, 5,
         bg=COLOR_DASH_BG, fg=COLOR_GOLD, bold=True, fs=12)
    _merge(svc, ss.id, ws.id, cur, 0, cur+1, 5)
    cur += 1

    # テーブルヘッダー
    _fmt(svc, ss.id, ws.id, cur, 0, cur+1, 5,
         bg=rgb(50,50,80), fg=COLOR_WHITE, bold=True, fs=10)
    cur += 1

    # テーブルデータ行（交互カラー）
    for i in range(len(ordered)):
        bg = COLOR_LIGHT_GRAY if i % 2 == 0 else COLOR_WHITE
        _fmt(svc, ss.id, ws.id, cur+i, 0, cur+i+1, 5, bg=bg, fs=10)

    # 列幅
    _col_widths(svc, ss.id, ws.id, [80, 260, 110, 110, 90])

    # ── グラフ（テーブル下に配置） ────────────────────
    # TDL グラフ
    tdl_start = tbl_data_start
    tdl_end   = tbl_data_start + len(tdl_rows)
    tds_start = tdl_end
    tds_end   = tdl_end + len(tds_rows)

    if tdl_rows:
        _add_bar_chart(svc, ss.id, ws.id,
                       tdl_start, tdl_end,
                       tdl_start, tdl_end,
                       col_domain=1, col_series=2,
                       anchor_row=tbl_data_end + 2, anchor_col=0,
                       title="🏯 TDL 現在の待ち時間（分）")

    if tds_rows:
        _add_bar_chart(svc, ss.id, ws.id,
                       tds_start, tds_end,
                       tds_start, tds_end,
                       col_domain=1, col_series=2,
                       anchor_row=tbl_data_end + 2, anchor_col=7,
                       title="🌊 TDS 現在の待ち時間（分）")

    # ダッシュボードを先頭タブに移動
    _move_front(svc, ss.id, ws.id)

    _flush(svc, ss.id)
    print(f"  ダッシュボード: 更新完了（TDL {len(tdl_rows)}本 / TDS {len(tds_rows)}本）")


# ══════════════════════════════════════════════════════
# メイン
# ══════════════════════════════════════════════════════
def main():
    now_jst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    print(f"=== Disney Tracker v2  {now_jst.strftime('%Y-%m-%d %H:%M')} JST ===")

    gc, svc = get_clients()
    ss = gc.open_by_key(SPREADSHEET_ID)

    all_ride_info: dict = {}
    summaries:     dict = {}

    for park_label, park_id in PARKS.items():
        key_rides = TDL_KEY_RIDES if park_label == "TDL" else TDS_KEY_RIDES
        print(f"\n[{park_label}] データ取得中...")
        try:
            data      = fetch_park(park_id)
            all_rides = flatten_rides(data)

            filtered = {}
            for ride_name in key_rides:
                info = all_rides.get(ride_name)
                filtered[ride_name] = ({**info, "park": park_label} if info
                                       else {"park": park_label, "is_open": False,
                                             "wait_time": 0, "land": "—"})
            all_ride_info.update(filtered)

            open_rides = [v for v in filtered.values()
                          if v["is_open"] and v["wait_time"] > 0]
            waits      = [v["wait_time"] for v in open_rides]
            avg_wait   = round(sum(waits)/len(waits), 1) if waits else 0
            max_r      = max(open_rides, key=lambda x: x["wait_time"]) if open_rides else {}
            max_name   = next((k for k, v in filtered.items() if v is max_r), "—")

            summaries[park_label] = {
                "avg_wait":     avg_wait,
                "max_wait":     max_r.get("wait_time", 0),
                "max_name":     max_name,
                "crowd":        estimate_crowd(avg_wait),
                "open_count":   len(open_rides),
                "closed_count": len([v for v in filtered.values() if not v["is_open"]]),
            }
            print(f"  運営中: {summaries[park_label]['open_count']} | "
                  f"平均待ち: {avg_wait}分 | 推定: {summaries[park_label]['crowd']}")
            time.sleep(1)
        except Exception as e:
            print(f"  ERROR: {e}")

    print("\n[Sheets] 書き込み中...")
    write_summary(ss, svc, now_jst, summaries)
    time.sleep(1)
    write_attraction_tabs(ss, svc, now_jst, all_ride_info)
    time.sleep(1)
    write_dashboard(ss, svc, now_jst, all_ride_info, summaries)
    print("\n✅ 完了！")


if __name__ == "__main__":
    main()
