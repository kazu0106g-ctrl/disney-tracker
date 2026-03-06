"""
ローカルテスト用スクリプト
Google Sheets に書き込まず、コンソールに結果を表示する。
動作確認・デバッグに使用。

使い方:
  pip install requests
  python scripts/test_fetch.py
"""

import requests
import datetime
import json

PARKS = {
    "TDL（東京ディズニーランド）": 274,
    "TDS（東京ディズニーシー）":   275,
}

CROWD_ESTIMATE = [
    (10,  "〜15,000人（超空き）"),
    (20,  "15,000〜25,000人（空き）"),
    (35,  "25,000〜35,000人（普通）"),
    (50,  "35,000〜50,000人（やや混雑）"),
    (70,  "50,000〜60,000人（混雑）"),
    (999, "60,000〜70,000人（激混み）"),
]

def estimate_crowd(avg_wait):
    for threshold, label in CROWD_ESTIMATE:
        if avg_wait <= threshold:
            return label
    return "60,000〜70,000人（激混み）"

def fetch_and_print(park_label, park_id):
    url = f"https://queue-times.com/parks/{park_id}/queue_times.json"
    print(f"\n{'='*55}")
    print(f"  {park_label}")
    print(f"{'='*55}")

    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  ERROR: {e}")
        return

    all_rides = []
    for land in data.get("lands", []):
        for ride in land.get("rides", []):
            all_rides.append({
                "land":      land["name"],
                "name":      ride["name"],
                "is_open":   ride["is_open"],
                "wait_time": ride["wait_time"],
            })

    open_rides = [r for r in all_rides if r["is_open"] and r["wait_time"] > 0]
    closed     = [r for r in all_rides if not r["is_open"]]
    waits      = [r["wait_time"] for r in open_rides]
    avg_wait   = round(sum(waits)/len(waits), 1) if waits else 0

    print(f"  取得日時  : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  運営中    : {len(open_rides)} アトラクション")
    print(f"  休止中    : {len(closed)} アトラクション")
    print(f"  平均待ち  : {avg_wait} 分")
    print(f"  推定入場者: {estimate_crowd(avg_wait)}")

    if open_rides:
        top5 = sorted(open_rides, key=lambda r: r["wait_time"], reverse=True)[:5]
        print(f"\n  ▼ 待ち時間 TOP5")
        for i, r in enumerate(top5, 1):
            print(f"    {i}. {r['name']:<30} {r['wait_time']:>3}分")

    print(f"\n  ▼ 全アトラクション一覧")
    for land_name in dict.fromkeys(r["land"] for r in all_rides):
        rides_in_land = [r for r in all_rides if r["land"] == land_name]
        print(f"\n  【{land_name}】")
        for r in rides_in_land:
            status = f"{r['wait_time']:>3}分待ち" if r["is_open"] and r["wait_time"] > 0 else ("運営中(0分)" if r["is_open"] else "休止中    ")
            print(f"    {'○' if r['is_open'] else '×'} {r['name']:<35} {status}")

if __name__ == "__main__":
    now = datetime.datetime.now()
    print(f"\n🏰 Disney Wait Time Fetcher — {now.strftime('%Y/%m/%d %H:%M')}")
    print("   データソース: queue-times.com (無料API)")
    print("   Powered by Queue-Times.com")

    for label, pid in PARKS.items():
        fetch_and_print(label, pid)

    print(f"\n{'='*55}")
    print("  完了！")
