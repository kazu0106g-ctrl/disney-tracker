"""
Disney Wait Time Collector
--------------------------
queue-times.com の無料API から東京ディズニーランド＆シーの
待ち時間を取得し、Google Sheets に記録する。

Park IDs:
  274 = Tokyo Disneyland (TDL)
  275 = Tokyo DisneySea  (TDS)
"""

import os
import json
import time
import datetime
import requests
import gspread
from google.oauth2.service_account import Credentials

# ──────────────────────────────────────────────
# 設定
# ──────────────────────────────────────────────
PARKS = {
    "TDL": 274,   # 東京ディズニーランド
    "TDS": 275,   # 東京ディズニーシー
}

# 推定入場者数マッピング（平均待ち時間 → 推定人数）
# TDL/TDS の最大収容人数はそれぞれ約 7 万人
CROWD_ESTIMATE = [
    (10,  "〜15,000人（超空き）"),
    (20,  "15,000〜25,000人（空き）"),
    (35,  "25,000〜35,000人（普通）"),
    (50,  "35,000〜50,000人（やや混雑）"),
    (70,  "50,000〜60,000人（混雑）"),
    (999, "60,000〜70,000人（激混み）"),
]

# スプレッドシート設定
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]   # GitHub Secrets から
SHEET_DETAIL   = "全アトラクション"              # シート名
SHEET_SUMMARY  = "サマリー"                      # シート名

# ──────────────────────────────────────────────
# Google Sheets 認証
# ──────────────────────────────────────────────
def get_gspread_client():
    creds_json = os.environ["GOOGLE_CREDENTIALS"]   # GitHub Secrets から（JSON文字列）
    creds_dict = json.loads(creds_json)
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

# ──────────────────────────────────────────────
# データ取得
# ──────────────────────────────────────────────
def fetch_park(park_id: int) -> dict:
    url = f"https://queue-times.com/parks/{park_id}/queue_times.json"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()

def flatten_rides(data: dict) -> list[dict]:
    """lands 階層を平坦化してライド一覧を返す"""
    rides = []
    for land in data.get("lands", []):
        for ride in land.get("rides", []):
            rides.append({
                "land":         land["name"],
                "name":         ride["name"],
                "is_open":      ride["is_open"],
                "wait_time":    ride["wait_time"],
                "last_updated": ride.get("last_updated", ""),
            })
    # トップレベル rides
    for ride in data.get("rides", []):
        rides.append({
            "land":         "—",
            "name":         ride["name"],
            "is_open":      ride["is_open"],
            "wait_time":    ride["wait_time"],
            "last_updated": ride.get("last_updated", ""),
        })
    return rides

def estimate_crowd(avg_wait: float) -> str:
    for threshold, label in CROWD_ESTIMATE:
        if avg_wait <= threshold:
            return label
    return "60,000〜70,000人（激混み）"

def calc_summary(rides: list[dict], park_label: str) -> dict:
    open_rides   = [r for r in rides if r["is_open"] and r["wait_time"] > 0]
    closed_rides = [r for r in rides if not r["is_open"]]
    waits        = [r["wait_time"] for r in open_rides]
    avg_wait     = round(sum(waits) / len(waits), 1) if waits else 0
    max_ride     = max(open_rides, key=lambda r: r["wait_time"]) if open_rides else {}
    return {
        "park":         park_label,
        "open_count":   len(open_rides),
        "closed_count": len(closed_rides),
        "avg_wait":     avg_wait,
        "max_wait":     max_ride.get("wait_time", 0),
        "max_name":     max_ride.get("name", "—"),
        "crowd":        estimate_crowd(avg_wait),
    }

# ──────────────────────────────────────────────
# シートに書き込む
# ──────────────────────────────────────────────
def ensure_headers(ws, headers: list[str]):
    """先頭行がヘッダーでなければ挿入する"""
    try:
        first = ws.row_values(1)
    except Exception:
        first = []
    if first != headers:
        ws.insert_row(headers, index=1)

def write_detail(gc, now_jst: datetime.datetime, all_rides: list[dict]):
    """全アトラクション待ち時間シートに追記"""
    ss  = gc.open_by_key(SPREADSHEET_ID)
    try:
        ws = ss.worksheet(SHEET_DETAIL)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=SHEET_DETAIL, rows=5000, cols=10)

    headers = ["日時(JST)", "パーク", "エリア", "アトラクション名",
               "運営中", "待ち時間(分)", "最終更新"]
    ensure_headers(ws, headers)

    rows = []
    for r in all_rides:
        rows.append([
            now_jst.strftime("%Y-%m-%d %H:%M"),
            r["park"],
            r["land"],
            r["name"],
            "○" if r["is_open"] else "×",
            r["wait_time"] if r["is_open"] else "",
            r["last_updated"],
        ])
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    print(f"  詳細: {len(rows)} 行追記")

def write_summary(gc, now_jst: datetime.datetime, summaries: list[dict]):
    """サマリーシートに追記"""
    ss  = gc.open_by_key(SPREADSHEET_ID)
    try:
        ws = ss.worksheet(SHEET_SUMMARY)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=SHEET_SUMMARY, rows=5000, cols=10)

    headers = ["日時(JST)", "パーク", "運営中アトラクション数",
               "休止中", "平均待ち時間(分)", "最長待ち(分)",
               "最長待ちアトラクション", "推定入場者数"]
    ensure_headers(ws, headers)

    rows = []
    for s in summaries:
        rows.append([
            now_jst.strftime("%Y-%m-%d %H:%M"),
            s["park"],
            s["open_count"],
            s["closed_count"],
            s["avg_wait"],
            s["max_wait"],
            s["max_name"],
            s["crowd"],
        ])
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    print(f"  サマリー: {len(rows)} 行追記")

# ──────────────────────────────────────────────
# メイン
# ──────────────────────────────────────────────
def main():
    now_jst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    print(f"=== Disney Tracker {now_jst.strftime('%Y-%m-%d %H:%M')} JST ===")

    gc = get_gspread_client()

    all_rides  = []
    summaries  = []

    for park_label, park_id in PARKS.items():
        print(f"\n[{park_label}] データ取得中...")
        try:
            data  = fetch_park(park_id)
            rides = flatten_rides(data)
            for r in rides:
                r["park"] = park_label

            summary = calc_summary(rides, park_label)
            summaries.append(summary)
            all_rides.extend(rides)

            print(f"  運営中: {summary['open_count']} | 平均待ち: {summary['avg_wait']}分 | 推定: {summary['crowd']}")
            time.sleep(2)   # API への礼儀
        except Exception as e:
            print(f"  ERROR: {e}")

    print("\n[Sheets] 書き込み中...")
    write_detail(gc, now_jst, all_rides)
    write_summary(gc, now_jst, summaries)
    print("\n完了！")

if __name__ == "__main__":
    main()
