#!/usr/bin/env python3
"""
ABR（アドレス・ベース・レジストリ）データを都道府県単位の SQLite DB にビルドする。

Usage:
  python3 build.py --pref 13          # 東京都のみ
  python3 build.py --all              # 全都道府県
  python3 build.py --all --no-parcel  # 地番データを除く
  python3 build.py --list-prefs       # 利用可能な都道府県一覧
"""

import argparse
import csv
import gzip
import io
import json
import os
import re
import sqlite3
import sys
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DCAT_US_URL = "https://dataset.address-br.digital.go.jp/api/feed/dcat-us/1.1.json"

# CKAN package IDs → dataset names
PACKAGES = {
    "000002": "city",        # 市区町村マスター
    "000003": "town",        # 町字マスター
    "000004": "rsdt_blk",   # 住居表示-街区マスター
    "000005": "rsdt_dsp",   # 住居表示-住居マスター
    "000006": "town_pos",   # 町字位置参照拡張
    "000007": "rsdt_blk_pos", # 街区位置参照拡張
    "000008": "rsdt_dsp_pos", # 住居位置参照拡張
    "000010": "parcel",      # 地番マスター
    "000011": "parcel_pos",  # 地番位置参照拡張
    "000013": "city_pos",    # 市区町村位置参照拡張
}

PREF_NAMES = {
    "01": "hokkaido",   "02": "aomori",    "03": "iwate",
    "04": "miyagi",     "05": "akita",     "06": "yamagata",
    "07": "fukushima",  "08": "ibaraki",   "09": "tochigi",
    "10": "gunma",      "11": "saitama",   "12": "chiba",
    "13": "tokyo",      "14": "kanagawa",  "15": "niigata",
    "16": "toyama",     "17": "ishikawa",  "18": "fukui",
    "19": "yamanashi",  "20": "nagano",    "21": "gifu",
    "22": "shizuoka",   "23": "aichi",     "24": "mie",
    "25": "shiga",      "26": "kyoto",     "27": "osaka",
    "28": "hyogo",      "29": "nara",      "30": "wakayama",
    "31": "tottori",    "32": "shimane",   "33": "okayama",
    "34": "hiroshima",  "35": "yamaguchi", "36": "tokushima",
    "37": "kagawa",     "38": "ehime",     "39": "kochi",
    "40": "fukuoka",    "41": "saga",      "42": "nagasaki",
    "43": "kumamoto",   "44": "oita",      "45": "miyazaki",
    "46": "kagoshima",  "47": "okinawa",
}

DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS city (
    city_key INTEGER PRIMARY KEY,
    lg_code  TEXT UNIQUE NOT NULL,
    county   TEXT,
    city     TEXT NOT NULL,
    ward     TEXT,
    rep_lat  REAL,
    rep_lon  REAL
);

CREATE TABLE IF NOT EXISTS town (
    town_key       INTEGER PRIMARY KEY,
    city_key       INTEGER NOT NULL REFERENCES city(city_key),
    machiaza_id    TEXT NOT NULL,
    oaza_cho       TEXT,
    chome          TEXT,
    koaza          TEXT,
    rsdt_addr_flg  TEXT,
    koaza_aka_code TEXT,
    rep_lat        REAL,
    rep_lon        REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_town_city_machiaza ON town(city_key, machiaza_id);

CREATE TABLE IF NOT EXISTS rsdt_blk (
    rsdtblk_key INTEGER PRIMARY KEY,
    town_key    INTEGER NOT NULL REFERENCES town(town_key),
    blk_id      TEXT NOT NULL,
    blk_num     TEXT,
    rep_lat     REAL,
    rep_lon     REAL
);
CREATE INDEX IF NOT EXISTS idx_rsdt_blk_town ON rsdt_blk(town_key);

CREATE TABLE IF NOT EXISTS rsdt_dsp (
    rsdtdsp_key INTEGER PRIMARY KEY,
    rsdtblk_key INTEGER NOT NULL REFERENCES rsdt_blk(rsdtblk_key),
    rsdt_id     TEXT NOT NULL,
    rsdt2_id    TEXT,
    rsdt_num    TEXT,
    rsdt_num2   TEXT,
    rep_lat     REAL,
    rep_lon     REAL
);
CREATE INDEX IF NOT EXISTS idx_rsdt_dsp_blk ON rsdt_dsp(rsdtblk_key);

CREATE TABLE IF NOT EXISTS parcel (
    parcel_key INTEGER PRIMARY KEY,
    town_key   INTEGER REFERENCES town(town_key),
    prc_id     TEXT NOT NULL,
    prc_num1   TEXT,
    prc_num2   TEXT,
    prc_num3   TEXT,
    rep_lat    REAL,
    rep_lon    REAL
);
CREATE INDEX IF NOT EXISTS idx_parcel_town ON parcel(town_key);
"""


def log(msg: str):
    print(msg, flush=True)


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def fetch_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def parse_dcat_us(feed: dict) -> dict[str, list[str]]:
    """DCAT-US フィードから packageId → [downloadURL] のマッピングを返す"""
    result: dict[str, list[str]] = {}
    for dataset in feed.get("dataset", []):
        pkg_id = dataset.get("identifier", "")
        urls = []
        for dist in dataset.get("distribution", []):
            url = dist.get("downloadURL") or dist.get("accessURL")
            if url:
                urls.append(url)
        if pkg_id in PACKAGES:
            result[pkg_id] = urls
    return result


def pref_code_from_lg_code(lg_code: str) -> str:
    return lg_code[:2].zfill(2)


def float_or_none(v: str) -> float | None:
    try:
        return float(v) if v and v.strip() else None
    except ValueError:
        return None


def read_csv_from_zip(zip_bytes: bytes) -> list[dict]:
    rows = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if name.lower().endswith(".csv"):
                with zf.open(name) as f:
                    reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                    rows.extend(reader)
    return rows


def filter_rows_by_pref(rows: list[dict], pref_code: str, lg_col: str = "lg_code") -> list[dict]:
    return [r for r in rows if r.get(lg_col, "")[:2].zfill(2) == pref_code]


def build_pref_db(pref_code: str, pkg_urls: dict[str, list[str]],
                  out_dir: Path, include_parcel: bool = True):
    pref_name = PREF_NAMES.get(pref_code, pref_code)
    db_path = out_dir / f"{pref_code}_{pref_name}.db"
    log(f"[{pref_code}] Building {db_path.name} ...")

    if db_path.exists():
        db_path.unlink()

    con = sqlite3.connect(str(db_path))
    con.executescript(DDL)

    city_key_map: dict[str, int] = {}
    town_key_map: dict[tuple, int] = {}
    rsdtblk_key_map: dict[tuple, int] = {}

    # ── city ──────────────────────────────────────────────
    city_rows = _download_rows_for_pref(pkg_urls, "000002", pref_code)
    city_pos = {
        r["lg_code"]: r
        for r in _download_rows_for_pref(pkg_urls, "000013", pref_code)
    }

    city_inserts = []
    for r in city_rows:
        lg = r.get("lg_code", "")
        if pref_code_from_lg_code(lg) != pref_code:
            continue
        pos = city_pos.get(lg, {})
        city_inserts.append((
            lg,
            r.get("county") or None,
            r.get("city") or "",
            r.get("ward") or None,
            float_or_none(pos.get("rep_lat") or pos.get("REP_LAT") or ""),
            float_or_none(pos.get("rep_lon") or pos.get("REP_LON") or ""),
        ))

    con.executemany(
        "INSERT OR IGNORE INTO city(lg_code,county,city,ward,rep_lat,rep_lon) VALUES (?,?,?,?,?,?)",
        city_inserts,
    )
    for row in con.execute("SELECT city_key, lg_code FROM city"):
        city_key_map[row[1]] = row[0]
    log(f"[{pref_code}]   city: {len(city_key_map)}")

    # ── town ──────────────────────────────────────────────
    town_rows = _download_rows_for_pref(pkg_urls, "000003", pref_code)
    town_pos_map = {
        (r.get("lg_code", ""), r.get("machiaza_id", "")): r
        for r in _download_rows_for_pref(pkg_urls, "000006", pref_code)
    }

    town_inserts = []
    for r in town_rows:
        lg = r.get("lg_code", "")
        mid = r.get("machiaza_id", "")
        ck = city_key_map.get(lg)
        if ck is None:
            continue
        pos = town_pos_map.get((lg, mid), {})
        town_inserts.append((
            ck, mid,
            r.get("oaza_cho") or None,
            r.get("chome") or None,
            r.get("koaza") or None,
            r.get("rsdt_addr_flg") or None,
            r.get("koaza_aka_code") or None,
            float_or_none(pos.get("rep_lat") or pos.get("REP_LAT") or ""),
            float_or_none(pos.get("rep_lon") or pos.get("REP_LON") or ""),
        ))

    con.executemany(
        """INSERT OR IGNORE INTO town
           (city_key,machiaza_id,oaza_cho,chome,koaza,rsdt_addr_flg,koaza_aka_code,rep_lat,rep_lon)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        town_inserts,
    )
    for row in con.execute("SELECT town_key, city_key, machiaza_id FROM town"):
        town_key_map[(row[1], row[2])] = row[0]
    log(f"[{pref_code}]   town: {len(town_key_map)}")

    # ── rsdt_blk ──────────────────────────────────────────
    blk_rows = _download_rows_for_pref(pkg_urls, "000004", pref_code)
    blk_pos_map = {
        (r.get("lg_code", ""), r.get("machiaza_id", ""), r.get("blk_id", "")): r
        for r in _download_rows_for_pref(pkg_urls, "000007", pref_code)
    }

    blk_inserts = []
    for r in blk_rows:
        lg = r.get("lg_code", "")
        mid = r.get("machiaza_id", "")
        blk_id = r.get("blk_id", "")
        ck = city_key_map.get(lg)
        if ck is None:
            continue
        tk = town_key_map.get((ck, mid))
        if tk is None:
            continue
        pos = blk_pos_map.get((lg, mid, blk_id), {})
        blk_inserts.append((
            tk, blk_id,
            r.get("blk_num") or None,
            float_or_none(pos.get("rep_lat") or pos.get("REP_LAT") or ""),
            float_or_none(pos.get("rep_lon") or pos.get("REP_LON") or ""),
        ))

    con.executemany(
        "INSERT OR IGNORE INTO rsdt_blk(town_key,blk_id,blk_num,rep_lat,rep_lon) VALUES (?,?,?,?,?)",
        blk_inserts,
    )
    for row in con.execute("SELECT rsdtblk_key, town_key, blk_id FROM rsdt_blk"):
        rsdtblk_key_map[(row[1], row[2])] = row[0]
    log(f"[{pref_code}]   rsdt_blk: {len(rsdtblk_key_map)}")

    # ── rsdt_dsp ──────────────────────────────────────────
    dsp_rows = _download_rows_for_pref(pkg_urls, "000005", pref_code)
    dsp_pos_map = {
        (r.get("lg_code", ""), r.get("machiaza_id", ""), r.get("blk_id", ""), r.get("rsdt_id", ""), r.get("rsdt2_id", "")): r
        for r in _download_rows_for_pref(pkg_urls, "000008", pref_code)
    }

    dsp_inserts = []
    for r in dsp_rows:
        lg = r.get("lg_code", "")
        mid = r.get("machiaza_id", "")
        blk_id = r.get("blk_id", "")
        ck = city_key_map.get(lg)
        if ck is None:
            continue
        tk = town_key_map.get((ck, mid))
        if tk is None:
            continue
        bk = rsdtblk_key_map.get((tk, blk_id))
        if bk is None:
            continue
        rsdt_id = r.get("rsdt_id", "")
        rsdt2_id = r.get("rsdt2_id", "")
        pos = dsp_pos_map.get((lg, mid, blk_id, rsdt_id, rsdt2_id), {})
        dsp_inserts.append((
            bk, rsdt_id, rsdt2_id or None,
            r.get("rsdt_num") or None,
            r.get("rsdt_num2") or None,
            float_or_none(pos.get("rep_lat") or pos.get("REP_LAT") or ""),
            float_or_none(pos.get("rep_lon") or pos.get("REP_LON") or ""),
        ))

    con.executemany(
        """INSERT OR IGNORE INTO rsdt_dsp
           (rsdtblk_key,rsdt_id,rsdt2_id,rsdt_num,rsdt_num2,rep_lat,rep_lon)
           VALUES (?,?,?,?,?,?,?)""",
        dsp_inserts,
    )
    log(f"[{pref_code}]   rsdt_dsp: {len(dsp_inserts)}")

    # ── parcel ────────────────────────────────────────────
    if include_parcel:
        prc_rows = _download_rows_for_pref(pkg_urls, "000010", pref_code)
        prc_pos_map = {
            (r.get("lg_code", ""), r.get("machiaza_id", ""), r.get("prc_id", "")): r
            for r in _download_rows_for_pref(pkg_urls, "000011", pref_code)
        }

        prc_inserts = []
        for r in prc_rows:
            lg = r.get("lg_code", "")
            mid = r.get("machiaza_id", "")
            prc_id = r.get("prc_id", "")
            ck = city_key_map.get(lg)
            tk = town_key_map.get((ck, mid)) if ck else None
            pos = prc_pos_map.get((lg, mid, prc_id), {})
            prc_inserts.append((
                tk, prc_id,
                r.get("prc_num1") or None,
                r.get("prc_num2") or None,
                r.get("prc_num3") or None,
                float_or_none(pos.get("rep_lat") or pos.get("REP_LAT") or ""),
                float_or_none(pos.get("rep_lon") or pos.get("REP_LON") or ""),
            ))

        con.executemany(
            "INSERT OR IGNORE INTO parcel(town_key,prc_id,prc_num1,prc_num2,prc_num3,rep_lat,rep_lon) VALUES (?,?,?,?,?,?,?)",
            prc_inserts,
        )
        log(f"[{pref_code}]   parcel: {len(prc_inserts)}")

    con.execute("INSERT OR REPLACE INTO meta VALUES ('pref_code', ?)", (pref_code,))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('pref_name_en', ?)", (pref_name,))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('source', 'デジタル庁 アドレス・ベース・レジストリ')")
    con.execute("INSERT OR REPLACE INTO meta VALUES ('dcat_us_url', ?)", (DCAT_US_URL,))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('include_parcel', ?)", (str(include_parcel).lower(),))
    con.commit()
    con.close()

    gz_path = db_path.with_suffix(".db.gz")
    with open(db_path, "rb") as f_in, gzip.open(str(gz_path), "wb") as f_out:
        f_out.write(f_in.read())
    db_path.unlink()

    size_mb = gz_path.stat().st_size / 1024 / 1024
    log(f"[{pref_code}] Done → {gz_path.name} ({size_mb:.1f} MB)")
    return gz_path


_download_cache: dict[str, list[dict]] = {}

def _download_rows_for_pref(pkg_urls: dict[str, list[str]], pkg_id: str, pref_code: str) -> list[dict]:
    """指定 package の全 URL をダウンロードし、pref_code に属する行のみ返す"""
    if pkg_id not in pkg_urls:
        return []

    all_rows = []
    for url in pkg_urls[pkg_id]:
        cache_key = f"{url}:{pref_code}"
        if cache_key in _download_cache:
            all_rows.extend(_download_cache[cache_key])
            continue

        # URL から都道府県コードを検出してスキップ最適化
        url_pref = _extract_pref_from_url(url)
        if url_pref and url_pref != pref_code:
            _download_cache[cache_key] = []
            continue

        try:
            data = fetch_bytes(url)
            rows = read_csv_from_zip(data)
            filtered = filter_rows_by_pref(rows, pref_code)
            _download_cache[cache_key] = filtered
            all_rows.extend(filtered)
        except Exception as e:
            log(f"  WARNING: failed to download {url}: {e}")
            _download_cache[cache_key] = []

    return all_rows


def _extract_pref_from_url(url: str) -> str | None:
    """URL から都道府県コードを抽出する (例: mt_blk_pref13_... → "13")"""
    m = re.search(r"pref(\d{2})", url)
    if m:
        return m.group(1).zfill(2)
    # パスの /NN/ 形式 (例: /13/000004/...)
    m = re.search(r"/(\d{2})/\d{6}", url)
    if m:
        return m.group(1).zfill(2)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pref", help="都道府県コード (例: 13)")
    parser.add_argument("--all", action="store_true", help="全都道府県をビルド")
    parser.add_argument("--no-parcel", action="store_true", help="地番データを含めない")
    parser.add_argument("--out", default="dist", help="出力ディレクトリ")
    parser.add_argument("--list-prefs", action="store_true")
    args = parser.parse_args()

    if args.list_prefs:
        for code, name in sorted(PREF_NAMES.items()):
            print(f"{code}  {name}")
        return

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    include_parcel = not args.no_parcel

    log("Fetching DCAT-US feed ...")
    feed = fetch_json(DCAT_US_URL)
    pkg_urls = parse_dcat_us(feed)
    log(f"Found packages: {list(pkg_urls.keys())}")

    if args.all:
        prefs = sorted(PREF_NAMES.keys())
    elif args.pref:
        code = args.pref.zfill(2)
        if code not in PREF_NAMES:
            print(f"Unknown pref code: {code}", file=sys.stderr)
            sys.exit(1)
        prefs = [code]
    else:
        parser.print_help()
        sys.exit(1)

    for pref_code in prefs:
        build_pref_db(pref_code, pkg_urls, out_dir, include_parcel)

    log("All done.")


if __name__ == "__main__":
    main()
