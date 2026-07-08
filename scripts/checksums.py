#!/usr/bin/env python3
"""
dist/ 内の *.meta.json を読み取り、sha256sums.json を生成する。

Usage:
  python3 checksums.py [--dist dist] [--out sha256sums.json]
"""

import argparse
import json
import sys
from pathlib import Path

PREF_NAMES_JA = {
    "01": "北海道",   "02": "青森県",   "03": "岩手県",
    "04": "宮城県",   "05": "秋田県",   "06": "山形県",
    "07": "福島県",   "08": "茨城県",   "09": "栃木県",
    "10": "群馬県",   "11": "埼玉県",   "12": "千葉県",
    "13": "東京都",   "14": "神奈川県", "15": "新潟県",
    "16": "富山県",   "17": "石川県",   "18": "福井県",
    "19": "山梨県",   "20": "長野県",   "21": "岐阜県",
    "22": "静岡県",   "23": "愛知県",   "24": "三重県",
    "25": "滋賀県",   "26": "京都府",   "27": "大阪府",
    "28": "兵庫県",   "29": "奈良県",   "30": "和歌山県",
    "31": "鳥取県",   "32": "島根県",   "33": "岡山県",
    "34": "広島県",   "35": "山口県",   "36": "徳島県",
    "37": "香川県",   "38": "愛媛県",   "39": "高知県",
    "40": "福岡県",   "41": "佐賀県",   "42": "長崎県",
    "43": "熊本県",   "44": "大分県",   "45": "宮崎県",
    "46": "鹿児島県", "47": "沖縄県",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default="dist")
    ap.add_argument("--out",  default="sha256sums.json")
    ap.add_argument("--merge", help="既存の sha256sums.json をマージして更新のみ上書き")
    args = ap.parse_args()

    dist = Path(args.dist)
    if not dist.exists():
        sys.exit(f"Directory not found: {dist}")

    # 既存の sha256sums.json があればロード（--merge 指定時）
    existing: dict = {}
    if args.merge:
        merge_path = Path(args.merge)
        if merge_path.exists():
            existing = json.loads(merge_path.read_text())

    files = dict(existing.get("files", {}))

    for meta_path in sorted(dist.glob("*.meta.json")):
        meta = json.loads(meta_path.read_text())
        pref_code = meta["pref_code"]
        files[pref_code] = {
            "pref_code":    pref_code,
            "pref_ja":      PREF_NAMES_JA.get(pref_code, ""),
            "pref_name_en": meta["pref_name_en"],
            "sha256":       meta["sha256"],
            "size":         meta["size"],
            "parts":        meta["parts"],
        }
        print(f"{meta['sha256']}  {pref_code} ({', '.join(meta['parts'])})")

    result = {"files": dict(sorted(files.items()))}
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nWrote {args.out} ({len(files)} prefectures)")


if __name__ == "__main__":
    main()
