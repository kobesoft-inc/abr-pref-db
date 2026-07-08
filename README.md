# abr-pref-db

デジタル庁 [アドレス・ベース・レジストリ（ABR）](https://registry.digital.go.jp/) を
都道府県単位の SQLite データベースにビルドし、毎月自動リリースします。

[abr-geocoder](https://github.com/digital-go-jp/abr-geocoder) と同等のスキーマで、
住所検索・逆ジオコーディングに利用できます。

## ダウンロード

毎月1つのバージョンリリース（`v2026.07` 形式）に全47都道府県を収録します。
50MB を超えるファイルは `.001` `.002` ... に分割されます。

### Step 1: チェックサムを確認する

```bash
curl -fSL -O https://github.com/kobesoft-inc/abr-pref-db/releases/latest/download/sha256sums.json
```

```bash
# ローカルファイルの SHA256 と比較（例: 東京都）
sha256sum 13_tokyo.db.gz
jq -r '.files["13"].sha256' sha256sums.json
# → 一致していれば更新不要
```

### Step 2: 必要な都道府県をダウンロードする

```bash
BASE=https://github.com/kobesoft-inc/abr-pref-db/releases/latest/download

# 単一ファイルの都道府県（parts が1件）
curl -fSL -O $BASE/27_osaka.db.gz
gunzip 27_osaka.db.gz

# 分割ファイルの都道府県（parts が複数）
curl -fSL -O $BASE/13_tokyo.db.gz.001
curl -fSL -O $BASE/13_tokyo.db.gz.002
curl -fSL -O $BASE/13_tokyo.db.gz.003
cat 13_tokyo.db.gz.* > 13_tokyo.db.gz && gunzip 13_tokyo.db.gz
```

`sha256sums.json` の `parts` フィールドでファイル名を確認できます：

```bash
jq '.files["13"].parts' sha256sums.json
# → ["13_tokyo.db.gz.001", "13_tokyo.db.gz.002", "13_tokyo.db.gz.003"]
```

## リリース構成

毎月1日に全都道府県をビルドし、前回リリースから変化があった場合のみ新しいリリース（`v2026.07` 形式）を作成します。
変化がなければリリースはスキップされます。

## sha256sums.json の形式

```json
{
  "files": {
    "13": {
      "pref_code": "13",
      "pref_ja": "東京都",
      "pref_name_en": "tokyo",
      "sha256": "abc123...",
      "size": 130438828,
      "parts": ["13_tokyo.db.gz.001", "13_tokyo.db.gz.002", "13_tokyo.db.gz.003"]
    },
    "27": {
      "pref_code": "27",
      "pref_ja": "大阪府",
      "pref_name_en": "osaka",
      "sha256": "def456...",
      "size": 45000000,
      "parts": ["27_osaka.db.gz"]
    }
  }
}
```

`parts` が1件なら単一ファイル、複数なら連結して使用します。

## スキーマ

各都道府県の SQLite DB は同一スキーマです。

```sql
-- 市区町村マスター
city (city_key, lg_code, county, city, ward, rep_lat, rep_lon)

-- 町字マスター
town (town_key, city_key→city, machiaza_id, oaza_cho, chome, koaza,
      rsdt_addr_flg, koaza_aka_code, rep_lat, rep_lon)

-- 住居表示-街区マスター
rsdt_blk (rsdtblk_key, town_key→town, blk_id, blk_num, rep_lat, rep_lon)

-- 住居表示-住居マスター
rsdt_dsp (rsdtdsp_key, rsdtblk_key→rsdt_blk, rsdt_id, rsdt2_id,
          rsdt_num, rsdt_num2, rep_lat, rep_lon)

-- 地番マスター (オプション、デフォルトは除外)
parcel (parcel_key, town_key→town, prc_id, prc_num1, prc_num2, prc_num3,
        rep_lat, rep_lon)

-- ビルド情報
meta (key, value)
```

## 使用例

```sql
-- 住所文字列を組み立てる
SELECT city.city || town.oaza_cho || town.chome || rsdt_blk.blk_num || '-' || rsdt_dsp.rsdt_num AS address,
       rsdt_dsp.rep_lat, rsdt_dsp.rep_lon
FROM rsdt_dsp
JOIN rsdt_blk USING (rsdtblk_key)
JOIN town     USING (town_key)
JOIN city     USING (city_key)
WHERE city.city = '千代田区'
  AND town.oaza_cho = '千代田'
LIMIT 10;

-- 座標から近い住所を探す (lat/lon インデックスが必要)
SELECT city.city, town.oaza_cho, rep_lat, rep_lon
FROM town
JOIN city USING (city_key)
WHERE rep_lat BETWEEN 35.68 AND 35.69
  AND rep_lon BETWEEN 139.75 AND 139.76;
```

## ローカルビルド

```bash
# 1都道府県のみ
python3 scripts/build.py --pref 13

# 全都道府県（地番なし）
python3 scripts/build.py --all --no-parcel

# 全都道府県（地番あり）
python3 scripts/build.py --all

# チェックサム生成
python3 scripts/checksums.py --dist dist/ --out dist/sha256sums.json
```

## 更新スケジュール

毎月1日に GitHub Actions が自動実行し、最新のデータでリビルド・リリースします。

手動実行は Actions タブの **Build and Release** → **Run workflow** から行えます。
特定の都道府県のみ再ビルドする場合はカンマ区切りで指定できます（例: `13,27,01`）。

## ライセンス

ソースデータ: [デジタル庁 アドレス・ベース・レジストリ利用規約](https://registry.digital.go.jp/terms)  
本リポジトリのスクリプト: MIT
