# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Convert a manually-downloaded SNPedia dump into the `rsid<TAB>magnitude` TSV
that `build_panel.py --snpedia` expects.

SNPedia's site blocks automated fetching (bot WAF), so you download it yourself
in a browser, then run this. It accepts:

  * a MediaWiki XML export  (.xml)   -- pages with <title>Rs1805007</title> ...
  * a JSON map of page title -> wikitext  (.json)
  * an already-correct rsid<TAB>magnitude TSV  (passed through unchanged)

    python tools/snpedia_to_tsv.py snpedia_dump.xml -o snpedia.tsv
    python tools/build_panel.py --targets ... --snpedia snpedia.tsv -o panel.json

SNPedia data is CC BY-NC-SA 3.0 (non-commercial). Do not redistribute it.
"""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET

MAG_RE = re.compile(r"magnitude\s*[=:]\s*([0-9]+(?:\.[0-9]+)?)", re.I)


def _rsid(title):
    t = (title or "").strip()
    return ("rs" + t[2:]) if t.lower().startswith("rs") else t


def _mag(text):
    m = MAG_RE.search(text or "")
    if not m:
        return None
    try:
        return int(float(m.group(1)))
    except ValueError:
        return None


def from_xml(path):
    """Yield (rsid, magnitude) from a MediaWiki XML export (streamed)."""
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag.endswith("page"):
            title = None
            text = ""
            for child in elem.iter():
                if child.tag.endswith("title") and title is None:
                    title = child.text
                elif child.tag.endswith("text") and child.text:
                    text = child.text
            if title:
                mag = _mag(text)
                if mag is not None:
                    yield _rsid(title), mag
            elem.clear()


def from_json(path):
    with open(path) as fh:
        data = json.load(fh)
    items = data.get("pages", data) if isinstance(data, dict) else data
    pairs = items.items() if isinstance(items, dict) else ((p.get("title"), p.get("text") or p.get("content")) for p in items)
    for title, content in pairs:
        mag = _mag(content)
        if mag is not None:
            yield _rsid(title), mag


def from_tsv(path):
    with open(path) as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2:
                try:
                    yield _rsid(parts[0]), int(float(parts[1]))
                except ValueError:
                    continue


def main():
    ap = argparse.ArgumentParser(description="Convert a SNPedia dump to rsid<TAB>magnitude.")
    ap.add_argument("input")
    ap.add_argument("-o", "--out", help="output path (default: stdout)")
    args = ap.parse_args()

    lower = args.input.lower()
    if lower.endswith(".xml"):
        rows = from_xml(args.input)
    elif lower.endswith(".json"):
        rows = from_json(args.input)
    else:
        rows = from_tsv(args.input)

    out_lines = [f"{rsid}\t{mag}\n" for rsid, mag in rows]
    if args.out:
        with open(args.out, "w") as fh:
            fh.writelines(out_lines)
        print(f"wrote {args.out} ({len(out_lines)} entries)")
    else:
        sys.stdout.writelines(out_lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
