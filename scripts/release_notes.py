#!/usr/bin/env python3
"""
dist/sha256sums.json からリリースノートを生成して release_notes.md に書き出す。

Usage:
  python3 release_notes.py --sums dist/sha256sums.json --repo kobesoft-inc/jp-abr-db
"""

import argparse
import json
import subprocess
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sums", default="dist/sha256sums.json")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="release_notes.md")
    args = ap.parse_args()

    sums = json.loads(Path(args.sums).read_text())
    date = subprocess.check_output(["date", "-u", "+%Y-%m-%d"]).decode().strip()

    lines = []
    for code, info in sorted(sums["files"].items()):
        parts = info["parts"]
        size_mb = info["size"] / 1024 / 1024
        if len(parts) == 1:
            files_str = f"`{parts[0]}`"
        else:
            files_str = " ".join(f"`{p}`" for p in parts)
        lines.append(
            f"| {info['pref_ja']} | {files_str} | {size_mb:.0f} MB"
            f" | `{info['sha256'][:16]}...` |"
        )

    base_url = f"https://github.com/{args.repo}/releases/latest/download"

    notes = f"""\
## デジタル庁 アドレス・ベース・レジストリ SQLite 版

**ビルド日:** {date}

### ダウンロード方法

```bash
# 1. チェックサムファイルを取得
curl -fSL -O {base_url}/sha256sums.json

# 2. 目的の都道府県を確認（例: 東京都 13）
jq '.files["13"]' sha256sums.json

# 3. ダウンロード（単一ファイルの場合）
curl -fSL -O {base_url}/13_tokyo.db.gz
gunzip 13_tokyo.db.gz

# 4. 分割ファイルの場合（parts が複数のとき）
curl -fSL -O {base_url}/13_tokyo.db.gz.001
curl -fSL -O {base_url}/13_tokyo.db.gz.002
cat 13_tokyo.db.gz.* > 13_tokyo.db.gz && gunzip 13_tokyo.db.gz
```

### ローカルファイルの更新チェック

```bash
sha256sum 13_tokyo.db.gz
jq -r '.files["13"].sha256' sha256sums.json
```

### 都道府県別ファイル一覧

| 都道府県 | ファイル | サイズ | SHA256 (先頭16桁) |
|---|---|---|---|
""" + "\n".join(lines)

    Path(args.out).write_text(notes)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
