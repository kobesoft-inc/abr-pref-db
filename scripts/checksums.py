#!/usr/bin/env python3
"""
dist/ 内の .db.gz ファイルの SHA256 チェックサムを計算し、
sha256sums.json を生成する。

Usage:
  python3 checksums.py [--dist dist] [--out sha256sums.json]
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

PREF_NAMES = {
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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", default="dist", help="DB ディレクトリ")
    parser.add_argument("--out", default="sha256sums.json", help="出力 JSON パス")
    args = parser.parse_args()

    dist = Path(args.dist)
    if not dist.exists():
        print(f"Directory not found: {dist}", file=sys.stderr)
        sys.exit(1)

    files = {}
    for db_gz in sorted(dist.glob("*.db.gz")):
        name = db_gz.name
        pref_code = name.split("_")[0]
        checksum = sha256_file(db_gz)
        files[name] = {
            "sha256": checksum,
            "size":   db_gz.stat().st_size,
            "pref_code": pref_code,
            "pref_ja":   PREF_NAMES.get(pref_code, ""),
        }
        print(f"{checksum}  {name}")

    result = {
        "files": files,
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nWrote {out_path} ({len(files)} files)")


if __name__ == "__main__":
    main()
