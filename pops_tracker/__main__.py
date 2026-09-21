"""Command line: python -m pops_tracker <command>

  update        full weekly flow (fetch POPS, discover bulletins, download new, extract, parse, match, QC, export)
  fetch-pops    download raw POPS dataset only
  discover      scrape the DOB index and update the bulletin registry only
  build         re-derive every processed output from what is already on disk (no network except geocoding new addresses)
  status        print registry / output summary
"""
import argparse
import json
import sys

import pandas as pd

from . import (accountability, bulletins as B, comptroller, config, extract as X, history, pipeline as PL,
               pops_master, pops_source, qc)
from .http import SourceBlocked, get


def cmd_fetch_pops(_):
    row = pops_source.download_raw()
    print(f"POPS raw: {row['status']} ({row['csv_file']}, source updated {row['source_rows_updated_at']})")
    pops_master.write()


def cmd_discover(_):
    html = get(config.DOB_INDEX_URL).text
    before = set(B.load_registry()["bulletin_id"])
    reg = B.discover(html)
    new = sorted(set(reg["bulletin_id"]) - before)
    n_links = len(B.parse_index(html))
    print(f"index links: {n_links}; registry: {len(reg)}; newly discovered: {new or 'none'}")
    return html, n_links, new


def cmd_build(args, n_links=None):
    reg = B.load_registry()
    for _, r in reg.iterrows():          # extraction is incremental: only bulletins without text yet
        if r["downloaded"] == "True" and not X.text_path(r["bulletin_id"]).exists():
            X.extract_bulletin(r["bulletin_id"], B.local_path(r["bulletin_id"]))
    master = pd.read_csv(config.POPS_MASTER, dtype=str, keep_default_na=False)
    actions, diags = PL.parse_all(reg)
    df = PL.enrich(actions, master, geocode=not getattr(args, "offline", False))
    PL.update_registry(reg, df, diags)
    pops = PL.export(df)
    audit = comptroller.write(master)
    acc = accountability.build(master, df, audit)
    rv = qc.build_review(df, master, B.load_registry(), diags, audit, n_links)
    counts = history.build(master, pops, audit)
    from . import site_export
    print("site data:", site_export.build())
    print(f"actions: {len(df)} | POPS-related records: {len(pops)} | open review items: {int((rv.status == 'open').sum())}")
    print("qc:", json.dumps(qc.summary(rv), indent=1))
    print("sqlite rows:", counts)


def cmd_update(args):
    """Never let a blocked DOB fetch hide everything else: rebuild from what is on disk, then exit non-zero."""
    cmd_fetch_pops(args)
    n_links, blocked = None, None
    try:
        _, n_links, new = cmd_discover(args)
        changed = B.download_missing(check_updates=True)
        print(f"downloaded/refreshed PDFs: {changed or 'none'}")
    except SourceBlocked as e:
        blocked = str(e)
        print(f"::error title=DOB source blocked::{blocked}")
        print("Continuing with the bulletins already on disk; DOB data was NOT refreshed this run.")
    cmd_build(args, n_links)
    return 3 if blocked else 0


def cmd_status(_):
    reg = B.load_registry()
    print(reg[["bulletin_id", "downloaded", "parsed", "n_enforcement_actions", "n_potential_pops_matches"]].tail(12).to_string(index=False))
    print(len(reg), "bulletins;", (reg.parsed == "True").sum(), "parsed")


def cmd_analyze(_):
    from . import analysis
    o = analysis.run()
    analysis.write_report(o)
    print("wrote reports/analysis.md and reports/analysis/*.csv")


def cmd_check(_):
    """CI gate: exit non-zero when the review file holds a structural problem that makes new data untrustworthy."""
    rv = pd.read_csv(config.MANUAL_REVIEW, dtype=str, keep_default_na=False)
    hard = rv[rv["issue_type"].isin(["structure_change_index", "structure_change_filename", "structure_change_marker",
                                     "failed_extraction", "download_failed", "duplicate_bulletin", "bulletin_month_unparsed"])]
    for _, r in hard.iterrows():
        print(f"::error title={r['issue_type']}::{r['bulletin_id']} {r['detail']}")
    print(f"{len(hard)} structural problem(s); {int((rv.status == 'open').sum())} open review items in total")
    return 1 if len(hard) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pops_tracker")
    ap.add_argument("command", choices=["update", "fetch-pops", "discover", "build", "status", "check", "analyze"])
    ap.add_argument("--offline", action="store_true", help="do not call the geocoder for uncached addresses")
    args = ap.parse_args(argv)
    return {"update": cmd_update, "fetch-pops": cmd_fetch_pops, "discover": cmd_discover, "build": cmd_build, "status": cmd_status,
     "check": cmd_check, "analyze": cmd_analyze}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
