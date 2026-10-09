#!/usr/bin/env python3
"""Enrich Truth Social posts with market, GDELT, and image alt-text data."""

from __future__ import annotations

import io
import logging
import time as sleep_time
import zipfile
from pathlib import Path

import pandas as pd
import requests

TS_TICKERS = {
    "^GSPC": "sp500",
    "DIA": "dia",
    "QQQ": "qqq",
    "DJT": "djt",
    "LMT": "lmt",
    "WAR": "war",
    "CNRG": "cnrg",
    "XLV": "xlv",
    "XPH": "xph",
    "GLD": "gld",
    "USO": "uso",
    "XLI": "xli",
    "EWW": "eww",
    "VGK": "vgk",
    "IBIT": "ibit",
    "FXI": "fxi",
    "TLT": "tlt",
    "UUP": "uup",
}


def enrich_truthsocial_media(
    updated: pd.DataFrame,
    log: logging.Logger,
    checkpoint_dir: Path,
    hf_api_key: str | None,
    tag: str = "[TruthSocial]",
) -> pd.DataFrame:
    """Add market, GDELT, and alt-text enrichments to a Truth Social dataset."""
    updated = updated.copy()

    try:
        import numpy as np
        import yfinance as yf

        post_dt = pd.to_datetime(updated["datetime"], utc=True, errors="coerce")
        min_date = updated["date"].min()
        all_dates = pd.date_range(min_date, pd.Timestamp.now()).strftime("%Y-%m-%d")

        for yf_ticker, col_prefix in TS_TICKERS.items():
            try:
                daily = yf.download(
                    yf_ticker,
                    start=min_date,
                    end=pd.Timestamp.now().strftime("%Y-%m-%d"),
                    progress=False,
                )
                if not daily.empty:
                    daily = daily.droplevel("Ticker", axis=1) if isinstance(daily.columns, pd.MultiIndex) else daily
                    if isinstance(daily.columns, pd.MultiIndex):
                        daily.columns = [c[0] if isinstance(c, tuple) else c for c in daily.columns]
                    daily.columns.name = None
                    daily.index = daily.index.strftime("%Y-%m-%d")
                    daily_full = daily[["Open", "Close"]].reindex(all_dates).ffill()
                    updated[f"{col_prefix}_open"] = updated["date"].map(daily_full["Open"]).round(2)
                    updated[f"{col_prefix}_close"] = updated["date"].map(daily_full["Close"]).round(2)

                intraday_cache = checkpoint_dir / f"{col_prefix}_intraday.parquet"
                frames = []
                for interval, period in [("1m", "7d"), ("5m", "60d"), ("1h", "730d")]:
                    data = yf.download(yf_ticker, period=period, interval=interval, progress=False)
                    if not data.empty:
                        data = data.droplevel("Ticker", axis=1) if isinstance(data.columns, pd.MultiIndex) else data
                        if isinstance(data.columns, pd.MultiIndex):
                            data.columns = [c[0] if isinstance(c, tuple) else c for c in data.columns]
                        data.columns.name = None
                        if "Close" in data.columns:
                            frames.append(data[["Close"]].rename(columns={"Close": "price"}))

                if frames:
                    intraday = pd.concat(frames).sort_index()
                    intraday = intraday[~intraday.index.duplicated(keep="first")]

                    if intraday_cache.exists():
                        old = pd.read_parquet(intraday_cache)
                        if "price" in old.columns:
                            intraday = pd.concat([old[["price"]], intraday]).sort_index()
                        else:
                            intraday = pd.concat([old, intraday]).sort_index()
                        intraday = intraday[~intraday.index.duplicated(keep="last")]

                    intraday.to_parquet(intraday_cache)

                    sp_sorted = intraday.reset_index()
                    sp_sorted.columns = ["sp_dt", "price"]
                    sp_sorted["sp_dt"] = pd.to_datetime(sp_sorted["sp_dt"], utc=True)

                    for offset_min, suffix, direction in [
                        (-60, "1hr_before", "backward"),
                        (-5, "5min_before", "backward"),
                        (0, "at_post", "backward"),
                        (5, "5min_after", "forward"),
                        (60, "1hr_after", "forward"),
                    ]:
                        col_name = f"{col_prefix}_{suffix}"
                        offset_dt = post_dt + pd.Timedelta(minutes=offset_min)
                        posts = pd.DataFrame({
                            "post_dt": pd.to_datetime(offset_dt, utc=True),
                            "orig_idx": updated.index,
                        }).dropna().sort_values("post_dt")
                        merged = pd.merge_asof(
                            posts,
                            sp_sorted,
                            left_on="post_dt",
                            right_on="sp_dt",
                            direction=direction,
                        )
                        updated[col_name] = np.nan
                        updated.loc[merged["orig_idx"].values, col_name] = merged["price"].round(2).values

                log.info(f"{tag} Merged {yf_ticker} ({col_prefix}) data")
            except Exception as e:
                log.warning(f"{tag} Could not merge {yf_ticker}: {e}")
    except ImportError:
        log.warning(f"{tag} yfinance not installed, skipping stock data")

    try:
        gdelt_cache = checkpoint_dir / "gdelt_daily.parquet"
        gdelt_existing = pd.read_parquet(gdelt_cache) if gdelt_cache.exists() else pd.DataFrame()

        all_post_dates = set(updated["date"].unique())
        existing_dates = set(gdelt_existing["date"].tolist()) if not gdelt_existing.empty else set()
        missing_dates = sorted(all_post_dates - existing_dates)

        if missing_dates:
            log.info(f"{tag} Fetching GDELT data for {len(missing_dates)} missing dates...")
            new_gdelt_rows = []
            for date_str in missing_dates[-30:]:
                ymd = date_str.replace("-", "")
                export_url = f"http://data.gdeltproject.org/events/{ymd}.export.CSV.zip"
                try:
                    sleep_time.sleep(1)
                    resp = requests.get(export_url, timeout=60)
                    if resp.status_code != 200:
                        continue
                    zf = zipfile.ZipFile(io.BytesIO(resp.content))
                    fname = zf.namelist()[0]
                    events = pd.read_csv(zf.open(fname), sep="\t", header=None, low_memory=False)
                    us = events[(events[7] == "USA") | (events[17] == "USA")]
                    if us.empty:
                        continue
                    row = {
                        "date": date_str,
                        "gdelt_military": int(us[us[28].isin(["18", "19", "20"])].shape[0]),
                        "gdelt_sanctions": int(us[us[28] == "17"].shape[0]),
                        "gdelt_threat": int(us[us[28] == "13"].shape[0]),
                        "gdelt_protest": int(us[us[28] == "14"].shape[0]),
                        "gdelt_force_posture": int(us[us[28] == "15"].shape[0]),
                        "gdelt_diplomatic": int(us[us[28].isin(["01", "02", "03", "04", "05", "06", "07", "08"])].shape[0]),
                        "gdelt_material_conflict": int(us[us[29] == 4].shape[0]),
                        "gdelt_verbal_conflict": int(us[us[29] == 3].shape[0]),
                        "gdelt_material_cooperation": int(us[us[29] == 2].shape[0]),
                        "gdelt_verbal_cooperation": int(us[us[29] == 1].shape[0]),
                        "gdelt_goldstein_avg": round(us[30].mean(), 2) if us[30].notna().any() else 0,
                        "gdelt_avg_tone": round(us[34].mean(), 2) if us[34].notna().any() else 0,
                        "gdelt_total_events": int(len(us)),
                    }
                    new_gdelt_rows.append(row)
                    log.info(f"{tag} GDELT {date_str}: {row['gdelt_total_events']} events")
                except Exception as e:
                    log.warning(f"{tag} GDELT fetch failed for {date_str}: {e}")

            if new_gdelt_rows:
                new_gdelt = pd.DataFrame(new_gdelt_rows)
                gdelt_existing = pd.concat([gdelt_existing, new_gdelt], ignore_index=True)
                gdelt_existing = gdelt_existing.drop_duplicates(subset=["date"], keep="last")
                gdelt_existing = gdelt_existing.sort_values("date").reset_index(drop=True)

        if not gdelt_existing.empty:
            gd = gdelt_existing.sort_values("date").copy()
            for col in [
                "gdelt_military",
                "gdelt_sanctions",
                "gdelt_threat",
                "gdelt_protest",
                "gdelt_force_posture",
                "gdelt_diplomatic",
            ]:
                gd[col + "_pct"] = (gd[col] / gd["gdelt_total_events"] * 100).round(2)
            for col in [
                "gdelt_military",
                "gdelt_sanctions",
                "gdelt_threat",
                "gdelt_protest",
                "gdelt_material_conflict",
            ]:
                mean = gd[col].mean()
                std = gd[col].std()
                gd[col + "_zscore"] = ((gd[col] - mean) / std).round(2) if std > 0 else 0
            for col in [
                "gdelt_military",
                "gdelt_sanctions",
                "gdelt_threat",
                "gdelt_protest",
                "gdelt_material_conflict",
                "gdelt_goldstein_avg",
                "gdelt_avg_tone",
            ]:
                gd[col + "_delta"] = gd[col].diff().round(2)

            gd.to_parquet(gdelt_cache, index=False)

            gd_indexed = gd.set_index("date")
            gdelt_cols = [c for c in gd.columns if c != "date"]
            for col in gdelt_cols:
                updated[col] = updated["date"].map(gd_indexed[col])
            log.info(f"{tag} Merged {len(gdelt_cols)} GDELT columns")
    except Exception as e:
        log.warning(f"{tag} Could not merge GDELT data: {e}")

    try:
        import cat_pol as pol

        if hf_api_key:
            needs_summary = updated[
                (updated["media_urls"].str.len() > 0)
                & (~updated["media_urls"].str.lower().str.endswith(".mp4"))
                & (updated.get("image_alt_text", pd.Series([""] * len(updated))).fillna("").str.len() == 0)
                & (pd.to_datetime(updated["datetime"], errors="coerce") >= "2024-11-05")
            ]
            if len(needs_summary) > 0:
                log.info(f"{tag} Summarizing {len(needs_summary)} new images...")
                for batch_start in range(0, len(needs_summary), 25):
                    batch = needs_summary.iloc[batch_start:batch_start + 25]

                    def pick_image(media_str: str) -> str:
                        for url in str(media_str).split(";"):
                            url = url.strip()
                            if url and not url.lower().endswith(".mp4"):
                                return url
                        return str(media_str).split(";")[0].strip()

                    batch_urls = [pick_image(url) for url in batch["media_urls"].tolist()]
                    try:
                        result = pol.summarize(
                            input_data=batch_urls,
                            format="alt-text",
                            tone=None,
                            user_model="qwen/qwen2.5-vl-72b-instruct:novita",
                            model_source="huggingface",
                            api_key=hf_api_key,
                            description="Images posted by Donald Trump on Truth Social",
                            thinking_budget=0,
                        )
                        for i, (orig_idx, _) in enumerate(batch.iterrows()):
                            if i < len(result) and result.iloc[i].get("processing_status") == "success":
                                updated.at[orig_idx, "image_alt_text"] = result.iloc[i].get("summary", "")
                        log.info(f"{tag} Image batch {batch_start // 25 + 1}: done")
                    except Exception as e:
                        log.warning(f"{tag} Image batch failed: {e}")
            else:
                log.info(f"{tag} No new images to summarize")
    except Exception as e:
        log.warning(f"{tag} Could not summarize images: {e}")

    return updated
