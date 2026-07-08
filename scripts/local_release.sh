#!/usr/bin/env bash
# ローカル（日本国内）でビルドして GitHub Releases にアップロードする。
#
# データ取得元の data.address-br.digital.go.jp は日本国内IPからのみアクセス可能なため、
# GitHub Actions ランナー（Azure 米国）ではなくローカルで実行する。
#
# 使い方:
#   bash scripts/local_release.sh            # 全都道府県
#   bash scripts/local_release.sh 13 27      # 指定都道府県のみ
#   FORCE=true bash scripts/local_release.sh # 変更なくても強制リリース

set -euo pipefail

REPO="kobesoft-inc/jp-abr-db"
DIST="dist"
TAG="v$(date -u '+%Y.%m')"

# ── 対象都道府県 ─────────────────────────────────────────────
if [ $# -gt 0 ]; then
    PREFS=("$@")
else
    PREFS=($(seq 1 47 | xargs printf '%02d '))
fi
echo "対象: ${PREFS[*]}"
echo "タグ: $TAG"

# ── ビルド ───────────────────────────────────────────────────
mkdir -p "$DIST"
for p in "${PREFS[@]}"; do
    echo ""
    echo "=== 都道府県 $p をビルド中 ==="
    python3 scripts/build.py --pref "$p" --out "$DIST/"
done

# ── チェックサム生成 ─────────────────────────────────────────
python3 scripts/checksums.py --dist "$DIST/" --out "$DIST/sha256sums.json"
echo ""
echo "=== sha256sums.json ==="
cat "$DIST/sha256sums.json"

# ── 変更チェック ─────────────────────────────────────────────
if [ "${FORCE:-false}" != "true" ]; then
    gh release download --repo "$REPO" \
        --pattern sha256sums.json \
        --output prev_sha256sums.json \
        --clobber 2>/dev/null || echo '{"files":{}}' > prev_sha256sums.json

    if diff -q prev_sha256sums.json "$DIST/sha256sums.json" > /dev/null 2>&1; then
        echo ""
        echo "変更なし。リリースをスキップします。（強制実行: FORCE=true bash $0）"
        rm -f prev_sha256sums.json
        exit 0
    fi
    rm -f prev_sha256sums.json
fi

# ── リリースノート生成 ────────────────────────────────────────
python3 scripts/release_notes.py \
    --sums "$DIST/sha256sums.json" \
    --repo "$REPO" \
    --out "$DIST/release_notes.md"

# ── GitHub Release 作成 ──────────────────────────────────────
echo ""
echo "=== リリース作成: $TAG ==="
gh release delete "$TAG" --repo "$REPO" --yes --cleanup-tag 2>/dev/null || true

gh release create "$TAG" "$DIST/"*.db.gz* "$DIST/sha256sums.json" \
    --repo "$REPO" \
    --title "アドレス・ベース・レジストリ $TAG" \
    --notes-file "$DIST/release_notes.md"

echo ""
echo "✅ リリース完了: https://github.com/$REPO/releases/tag/$TAG"

# ── sha256sums.json をリポジトリに保存 ───────────────────────
cp "$DIST/sha256sums.json" sha256sums.json
git add sha256sums.json
if git diff --cached --quiet; then
    echo "sha256sums.json に変更なし。"
else
    git commit -m "chore: update sha256sums.json [skip ci]"
    git push
fi
