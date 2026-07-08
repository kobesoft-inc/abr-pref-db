#!/usr/bin/env python3
"""
ABR（アドレス・ベース・レジストリ）データを都道府県単位の SQLite DB にビルドする。

データソース: https://data.address-br.digital.go.jp/{type}/pref/{type}_pref{NN}.csv.zip

Usage:
  python3 build.py --pref 13          # 東京都のみ
  python3 build.py --all              # 全都道府県
  python3 build.py --list-prefs       # 利用可能な都道府県一覧
"""

import argparse
import csv
import gzip
import io
import os
import sqlite3
import sys
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ABR_BASE = "https://data.address-br.digital.go.jp"

PREF_NAMES_EN = {
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
    post_code      TEXT,
    rep_lat        REAL,
    rep_lon        REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_town_city_machiaza ON town(city_key, machiaza_id);
CREATE INDEX IF NOT EXISTS idx_town_post_code ON town(post_code);

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


def pref_url(data_type: str, pref_code: str) -> str:
    return f"{ABR_BASE}/{data_type}/pref/{data_type}_pref{pref_code}.csv.zip"


def city_url(data_type: str, lg_code: str) -> str:
    return f"{ABR_BASE}/{data_type}/city/{data_type}_city{lg_code}.csv.zip"


def fetch_csv(url: str) -> list[dict]:
    log(f"  Downloading {url.split('/')[-1]} ...")
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log(f"  (404 - skipped)")
            return []
        raise
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        rows = []
        for name in zf.namelist():
            if name.lower().endswith(".csv"):
                with zf.open(name) as f:
                    reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                    rows.extend(reader)
    return rows


def real(v: str) -> float | None:
    try:
        return float(v) if v and v.strip() else None
    except ValueError:
        return None


def build(pref_code: str, out_dir: Path):
    name = PREF_NAMES_EN[pref_code]
    db_path = out_dir / f"{pref_code}_{name}.db"
    log(f"\n[{pref_code}] Building {db_path.name} ...")

    if db_path.exists():
        db_path.unlink()

    con = sqlite3.connect(str(db_path))
    con.executescript(DDL)

    # ── city ──────────────────────────────────────────────
    city_rows  = fetch_csv(pref_url("mt_city",     pref_code))
    city_pos   = {r["lg_code"]: r for r in fetch_csv(pref_url("mt_city_pos", pref_code))}

    con.executemany(
        "INSERT OR IGNORE INTO city(lg_code,county,city,ward,rep_lat,rep_lon) VALUES(?,?,?,?,?,?)",
        [
            (
                r["lg_code"],
                r.get("county") or None,
                r.get("city") or "",
                r.get("ward") or None,
                real(city_pos.get(r["lg_code"], {}).get("rep_lat", "")),
                real(city_pos.get(r["lg_code"], {}).get("rep_lon", "")),
            )
            for r in city_rows
        ],
    )
    city_key = {row[1]: row[0] for row in con.execute("SELECT city_key, lg_code FROM city")}
    log(f"  city: {len(city_key)}")

    # ── town ──────────────────────────────────────────────
    town_rows  = fetch_csv(pref_url("mt_town",     pref_code))
    town_pos   = {
        (r["lg_code"], r["machiaza_id"]): r
        for r in fetch_csv(pref_url("mt_town_pos", pref_code))
    }

    town_insert = []
    for r in town_rows:
        ck = city_key.get(r["lg_code"])
        if ck is None:
            continue
        mid = r["machiaza_id"]
        pos = town_pos.get((r["lg_code"], mid), {})
        town_insert.append((
            ck, mid,
            r.get("oaza_cho") or None,
            r.get("chome") or None,
            r.get("koaza") or None,
            r.get("rsdt_addr_flg") or None,
            r.get("koaza_aka_code") or None,
            r.get("post_code") or None,
            real(pos.get("rep_lat", "")),
            real(pos.get("rep_lon", "")),
        ))

    con.executemany(
        """INSERT OR IGNORE INTO town
           (city_key,machiaza_id,oaza_cho,chome,koaza,rsdt_addr_flg,
            koaza_aka_code,post_code,rep_lat,rep_lon)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        town_insert,
    )
    town_key = {
        (row[1], row[2]): row[0]
        for row in con.execute("SELECT town_key, city_key, machiaza_id FROM town")
    }
    log(f"  town: {len(town_key)}")

    # ── rsdt_blk ──────────────────────────────────────────
    blk_rows   = fetch_csv(pref_url("mt_rsdtdsp_blk",     pref_code))
    blk_pos    = {
        (r["lg_code"], r["machiaza_id"], r["blk_id"]): r
        for r in fetch_csv(pref_url("mt_rsdtdsp_blk_pos", pref_code))
    }

    blk_insert = []
    for r in blk_rows:
        ck = city_key.get(r["lg_code"])
        if ck is None:
            continue
        tk = town_key.get((ck, r["machiaza_id"]))
        if tk is None:
            continue
        pos = blk_pos.get((r["lg_code"], r["machiaza_id"], r["blk_id"]), {})
        blk_insert.append((
            tk,
            r["blk_id"],
            r.get("blk_num") or None,
            real(pos.get("rep_lat", "")),
            real(pos.get("rep_lon", "")),
        ))

    con.executemany(
        "INSERT OR IGNORE INTO rsdt_blk(town_key,blk_id,blk_num,rep_lat,rep_lon) VALUES(?,?,?,?,?)",
        blk_insert,
    )
    blk_key = {
        (row[1], row[2]): row[0]
        for row in con.execute("SELECT rsdtblk_key, town_key, blk_id FROM rsdt_blk")
    }
    log(f"  rsdt_blk: {len(blk_key)}")

    # ── rsdt_dsp ──────────────────────────────────────────
    dsp_rows   = fetch_csv(pref_url("mt_rsdtdsp_rsdt",     pref_code))
    dsp_pos    = {
        (r["lg_code"], r["machiaza_id"], r["blk_id"], r["rsdt_id"], r["rsdt2_id"]): r
        for r in fetch_csv(pref_url("mt_rsdtdsp_rsdt_pos", pref_code))
    }

    dsp_insert = []
    for r in dsp_rows:
        ck = city_key.get(r["lg_code"])
        if ck is None:
            continue
        tk = town_key.get((ck, r["machiaza_id"]))
        if tk is None:
            continue
        bk = blk_key.get((tk, r["blk_id"]))
        if bk is None:
            continue
        rsdt_id  = r["rsdt_id"]
        rsdt2_id = r.get("rsdt2_id", "")
        pos = dsp_pos.get((r["lg_code"], r["machiaza_id"], r["blk_id"], rsdt_id, rsdt2_id), {})
        dsp_insert.append((
            bk, rsdt_id, rsdt2_id or None,
            r.get("rsdt_num") or None,
            r.get("rsdt_num2") or None,
            real(pos.get("rep_lat", "")),
            real(pos.get("rep_lon", "")),
        ))

    con.executemany(
        """INSERT OR IGNORE INTO rsdt_dsp
           (rsdtblk_key,rsdt_id,rsdt2_id,rsdt_num,rsdt_num2,rep_lat,rep_lon)
           VALUES(?,?,?,?,?,?,?)""",
        dsp_insert,
    )
    log(f"  rsdt_dsp: {len(dsp_insert)}")

    # ── parcel (市区町村単位で並列ダウンロード) ────────────
    lg_codes = list(city_key.keys())

    def fetch_parcel_for_city(lg: str):
        rows = fetch_csv(city_url("mt_parcel", lg))
        pos  = {r["prc_id"]: r for r in fetch_csv(city_url("mt_parcel_pos", lg))}
        return lg, rows, pos

    parcel_insert = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_parcel_for_city, lg): lg for lg in lg_codes}
        for future in as_completed(futures):
            lg, rows, pos_map = future.result()
            ck = city_key.get(lg)
            if ck is None:
                continue
            for r in rows:
                mid   = r.get("machiaza_id", "")
                prc_id = r.get("prc_id", "")
                tk    = town_key.get((ck, mid))
                p     = pos_map.get(prc_id, {})
                parcel_insert.append((
                    tk, prc_id,
                    r.get("prc_num1") or None,
                    r.get("prc_num2") or None,
                    r.get("prc_num3") or None,
                    real(p.get("rep_lat", "")),
                    real(p.get("rep_lon", "")),
                ))

    con.executemany(
        "INSERT OR IGNORE INTO parcel(town_key,prc_id,prc_num1,prc_num2,prc_num3,rep_lat,rep_lon) VALUES(?,?,?,?,?,?,?)",
        parcel_insert,
    )
    log(f"  parcel: {len(parcel_insert)}")

    # ── meta ──────────────────────────────────────────────
    con.executemany("INSERT OR REPLACE INTO meta VALUES(?,?)", [
        ("pref_code",   pref_code),
        ("pref_name_en", name),
        ("source",      "デジタル庁 アドレス・ベース・レジストリ"),
        ("source_base", ABR_BASE),
    ])
    con.commit()
    con.close()

    gz = db_path.with_suffix(".db.gz")
    with open(db_path, "rb") as fi, gzip.open(str(gz), "wb") as fo:
        fo.write(fi.read())
    db_path.unlink()

    log(f"  → {gz.name} ({gz.stat().st_size / 1024 / 1024:.1f} MB)")
    return gz


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pref",       help="都道府県コード (例: 13)")
    ap.add_argument("--all",        action="store_true")
    ap.add_argument("--out",        default="dist")
    ap.add_argument("--list-prefs", action="store_true")
    args = ap.parse_args()

    if args.list_prefs:
        for code, en in sorted(PREF_NAMES_EN.items()):
            print(f"{code}  {en}")
        return

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.all:
        prefs = sorted(PREF_NAMES_EN.keys())
    elif args.pref:
        prefs = [args.pref.zfill(2)]
        if prefs[0] not in PREF_NAMES_EN:
            sys.exit(f"Unknown pref: {args.pref}")
    else:
        ap.print_help(); sys.exit(1)

    for pc in prefs:
        build(pc, out)

    log("\nAll done.")


if __name__ == "__main__":
    main()
