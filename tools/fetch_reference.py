# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Download reference data for the panel ETL, into a local cache.

Default mode is SMALL: it reads the curated `--targets` file(s) and fetches only
the records for those rsIDs, via each source's API. Use --full to download the
complete official files instead.

Nothing here runs during Stage 2. This is a deliberate, separate step so the
annotator stays offline, deterministic, and private. Files land in a cache
(outside the repo by default) with a manifest recording source/URL/date/sha256.

    # see what would be fetched, no network
    python tools/fetch_reference.py --targets data/targets.carrier.json --dry-run

    # fetch only what the panels need (default)
    python tools/fetch_reference.py --targets data/targets.carrier.json \
        --targets data/targets.traits.json --email you@example.com

    # download complete files instead
    python tools/fetch_reference.py --full --email you@example.com

Then build a panel from the cache:

    python tools/build_panel.py --targets data/targets.carrier.json \
        --cache ~/.cache/snp-insights -o data/panel.carrier.json

Terms (verify the current terms of each source; not legal advice):
  ClinVar/dbSNP  public domain (NCBI usage policy: identify yourself, be polite)
  gnomAD         free; some datasets carry extra terms
  GWAS Catalog   free (EMBL-EBI terms)
  SNPedia        CC BY-NC-SA 3.0 -- NON-COMMERCIAL, attribution + share-alike;
                 requires --accept-license. Not redistributed by this project.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone

# GRCh37 (hg19) RefSeq chromosome accessions, as returned by the dbSNP API.
GRCH37_ACCESSIONS = {
    "NC_000001.10": "1", "NC_000002.11": "2", "NC_000003.11": "3", "NC_000004.11": "4",
    "NC_000005.9": "5", "NC_000006.11": "6", "NC_000007.13": "7", "NC_000008.10": "8",
    "NC_000009.11": "9", "NC_000010.10": "10", "NC_000011.9": "11", "NC_000012.11": "12",
    "NC_000013.10": "13", "NC_000014.8": "14", "NC_000015.9": "15", "NC_000016.9": "16",
    "NC_000017.10": "17", "NC_000018.9": "18", "NC_000019.9": "19", "NC_000020.10": "20",
    "NC_000021.8": "21", "NC_000022.10": "22", "NC_000023.10": "X", "NC_000024.9": "Y",
    "NC_012920.1": "MT",
}

FULL_URLS = {
    "clinvar": "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz",
    "dbsnp": "https://ftp.ncbi.nlm.nih.gov/snp/latest_release/VCF/GCF_000001405.25.gz",
    "rsmerge": "https://ftp.ncbi.nlm.nih.gov/snp/organisms/human_9606/database/organism_data/RsMergeArch.bcp.gz",
    # gnomAD v2.1.1 exomes (GRCh37). Verify the current path on gnomad.broadinstitute.org.
    "gnomad": "https://storage.googleapis.com/gcp-public-data--gnomad/release/2.1.1/vcf/exomes/gnomad.exomes.r2.1.1.sites.vcf.bgz",
    "gwas": "https://ftp.ebi.ac.uk/pub/databases/gwas/releases/latest/gwas-catalog-associations_ontology-annotated-full.zip",
}

DBSNP_API = "https://api.ncbi.nlm.nih.gov/variation/v0/refsnp/"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
SNPEDIA_API = "https://www.snpedia.com/api.php"
GNOMAD_API = "https://gnomad.broadinstitute.org/api"


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def load_target_rsids(paths):
    rsids = []
    seen = set()
    for p in paths:
        with open(p) as fh:
            data = json.load(fh)
        for v in data.get("variants", []):
            rsid = v.get("rsid")
            if rsid and rsid not in seen:
                seen.add(rsid)
                rsids.append(rsid)
    return rsids


_LAST = [0.0]
MIN_INTERVAL = 0.4  # seconds between requests (NCBI allows ~3/s without a key)


def _throttle():
    dt = time.time() - _LAST[0]
    if dt < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - dt)
    _LAST[0] = time.time()


def _ua(email):
    return {"User-Agent": f"snp-insights/0.1 ({email or 'no-contact'})"}


def http_get(url, email=None, timeout=60, retries=5):
    for attempt in range(retries):
        _throttle()
        try:
            req = urllib.request.Request(url, headers=_ua(email))
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise


def http_get_json(url, email=None, timeout=60):
    return json.loads(http_get(url, email=email, timeout=timeout))


def http_post_json(url, payload, email=None, timeout=60, retries=5):
    body = json.dumps(payload).encode()
    for attempt in range(retries):
        _throttle()
        try:
            headers = {"Content-Type": "application/json"}
            headers.update(_ua(email))
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise


def eutils(path, email):
    """Append NCBI E-utilities tool/email/api_key parameters."""
    params = ["tool=snp-insights"]
    if email:
        params.append(f"email={urllib.parse.quote(email)}")
    key = os.environ.get("NCBI_API_KEY")
    if key:
        params.append(f"api_key={urllib.parse.quote(key)}")
    sep = "&" if "?" in path else "?"
    return f"{EUTILS}{path}{sep}{'&'.join(params)}"


# --------------------------------------------------------------------------- #
# small-set fetchers (per-record APIs)
# --------------------------------------------------------------------------- #

def fetch_dbsnp_small(rsids, email):
    """Return {rsid: (chromosome, position, ref, alt)} and a ClinVar-ready list."""
    out = {}
    for rsid in rsids:
        try:
            data = http_get_json(f"{DBSNP_API}{rsid[2:]}", email=email)
        except Exception as exc:  # noqa: BLE001
            print(f"  dbsnp {rsid}: {exc}", file=sys.stderr)
            continue
        placements = (data.get("primary_snapshot_data") or {}).get("placements_with_allele") or []
        for pl in placements:
            chrom = GRCH37_ACCESSIONS.get(pl.get("seq_id"))
            if not chrom:
                continue
            for a in pl.get("alleles") or []:
                spdi = (a.get("allele") or {}).get("spdi") or {}
                ref = spdi.get("deleted_sequence", "")
                alt = spdi.get("inserted_sequence", "")
                pos = spdi.get("position")
                if pos is None or not ref or ref == alt:
                    continue  # first allele is the reference (deleted == inserted)
                out[rsid] = (chrom, int(pos) + 1, ref, alt or ".")
                break
            if rsid in out:
                break
    return out


def _stars(status):
    s = (status or "").lower()
    if "practice guideline" in s:
        return 4
    if "expert panel" in s:
        return 3
    if "multiple submitters" in s and "no conflict" in s:
        return 2
    if "conflicting" in s or "single submitter" in s:
        return 1
    return 0


def fetch_clinvar_small(rsids, email):
    """Return {rsid: (significance, review_status)} via NCBI E-utilities.

    A variant has one record per submission; pick the strongest (most-reviewed,
    and not a bare 'other').
    """
    out = {}
    for rsid in rsids:
        try:
            search = http_get_json(eutils(f"esearch.fcgi?db=clinvar&term={urllib.parse.quote(rsid)}&retmode=json", email), email=email)
            ids = (search.get("esearchresult") or {}).get("idlist") or []
            if not ids:
                continue
            summ = http_get_json(eutils(f"esummary.fcgi?db=clinvar&id={','.join(ids)}&retmode=json", email), email=email)
            result = summ.get("result") or {}
            best, best_score = None, -1
            for uid in result.get("uids", []):
                rec = result.get(uid) or {}
                germ = rec.get("germline_classification") or {}
                sig = germ.get("description")
                review = germ.get("review_status") or ""
                if not sig:
                    continue
                score = _stars(review) * 2 + (0 if sig.strip().lower() == "other" else 1)
                if score > best_score:
                    best_score, best = score, (sig, review)
            if best:
                out[rsid] = best
        except Exception as exc:  # noqa: BLE001
            print(f"  clinvar {rsid}: {exc}", file=sys.stderr)
    return out


def fetch_snpedia_small(rsids, email):
    """Return {rsid: magnitude} via the SNPedia MediaWiki API."""
    import re
    out = {}
    for rsid in rsids:
        try:
            url = (f"{SNPEDIA_API}?action=query&prop=revisions&rvprop=content&format=json"
                   f"&titles={urllib.parse.quote(rsid)}")
            data = http_get_json(url, email=email)
            pages = (data.get("query") or {}).get("pages") or {}
            for page in pages.values():
                content = ((page.get("revisions") or [{}])[0]).get("*", "")
                m = re.search(r"magnitude\s*=\s*([0-9.]+)", content, re.I)
                if m:
                    out[rsid] = int(float(m.group(1)))
        except Exception as exc:  # noqa: BLE001
            print(f"  snpedia {rsid}: {exc}", file=sys.stderr)
    return out


def fetch_gnomad_small(coords, email):
    """Return {rsid: af} via the gnomAD GraphQL API, keyed on coordinates."""
    out = {}
    for rsid, (chrom, pos, ref, alt) in coords.items():
        if len(ref) != 1 or len(alt) != 1 or ref not in "ACGT" or alt not in "ACGT":
            continue
        variant_id = f"{chrom}-{pos}-{ref}-{alt}"
        query = ("query($v: String!){ variant(variantId:$v, dataset:gnomad_r2_1){ "
                 "genome{ af } exome{ af } } }")
        try:
            data = http_post_json(GNOMAD_API, {"query": query, "variables": {"v": variant_id}}, email=email)
            var = (data.get("data") or {}).get("variant") or {}
            af = (var.get("genome") or {}).get("af")
            if af is None:
                af = (var.get("exome") or {}).get("af")
            if af is not None:
                out[rsid] = af
        except Exception as exc:  # noqa: BLE001
            print(f"  gnomad {rsid}: {exc}", file=sys.stderr)
    return out


# --------------------------------------------------------------------------- #
# GWAS: no per-rsID API; download the (comparatively small) full file and filter
# --------------------------------------------------------------------------- #

def _col_index(header):
    return {h.strip().lower(): i for i, h in enumerate(header)}


def _find_col(idx, *names):
    for n in names:
        i = idx.get(n.strip().lower())
        if i is not None:
            return i
    return None


def _gwas_matches(line, idx, wanted):
    i = _find_col(idx, "SNPS", "SNP", "SNP_ID_CURRENT", "SNP_ID")
    if i is None:
        return False
    row = line.rstrip("\n").split("\t")
    if i >= len(row) or not row[i]:
        return False
    tokens = row[i].replace(";", " ").replace(" x ", " ").split()
    return any(t in wanted for t in tokens)


def _filter_gwas(header, lines, wanted):
    idx = _col_index(header)
    return [line.rstrip("\n") for line in lines if _gwas_matches(line, idx, wanted)]


def fetch_gwas_small(wanted, email, cache):
    """Download the GWAS Catalog zip, filter its TSV to `wanted`, write gwas.tsv.

    The catalog ships a .zip containing one associations TSV; we extract inline
    and keep only rows whose SNPS column contains one of our rsIDs (exact token).
    """
    url = FULL_URLS["gwas"]
    zip_path = download_full("gwas", url, cache, email)
    out_path = os.path.join(cache, "gwas.tsv")
    header_out = ["SNPS", "PUBMEDID", "DISEASE/TRAIT"]
    count = 0
    with zipfile.ZipFile(zip_path) as z:
        member = next((n for n in z.namelist() if n.endswith(".tsv")), None)
        if not member:
            raise RuntimeError("no .tsv inside GWAS zip")
        with z.open(member) as raw, open(out_path, "w") as out:
            text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
            header = text.readline().rstrip("\n").lstrip("#").split("\t")
            idx = _col_index(header)
            snps_i = _find_col(idx, "SNPS", "SNP", "SNP_ID_CURRENT", "SNP_ID")
            pub_i = _find_col(idx, "PUBMEDID", "STUDY ACCESSION")
            trait_i = _find_col(idx, "DISEASE/TRAIT")
            out.write("\t".join(header_out) + "\n")
            for line in text:
                row = line.rstrip("\n").split("\t")
                snps = row[snps_i] if (snps_i is not None and snps_i < len(row)) else ""
                if not snps:
                    continue
                if any(t in wanted for t in snps.replace(";", " ").replace(" x ", " ").split()):
                    pub = row[pub_i] if (pub_i is not None and pub_i < len(row)) else ""
                    tr = row[trait_i] if (trait_i is not None and trait_i < len(row)) else ""
                    out.write(f"{snps}\t{pub}\t{tr}\n")
                    count += 1
    return count


def head_size(url, email):
    """Return Content-Length for a URL via HEAD, or None if unavailable."""
    headers = {"User-Agent": f"snp-insights/0.1 ({email or 'no-contact'})"}
    req = urllib.request.Request(url, method="HEAD", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        cl = resp.headers.get("Content-Length")
        return int(cl) if cl else None


# --------------------------------------------------------------------------- #
# writers (formats the ETL already reads)
# --------------------------------------------------------------------------- #

def write_dbsnp_tsv(path, coords):
    with open(path, "w") as fh:
        fh.write("rsid\tchromosome\tposition\treference_allele\talternate_allele\n")
        for rsid, (chrom, pos, ref, alt) in sorted(coords.items()):
            fh.write(f"{rsid}\t{chrom}\t{pos}\t{ref}\t{alt}\n")


def write_clinvar_tsv(path, clinvar):
    with open(path, "w") as fh:
        fh.write("RS# (dbSNP)\tAssembly\tReviewStatus\tClinicalSignificance\n")
        for rsid, (sig, review) in sorted(clinvar.items()):
            fh.write(f"{rsid}\tGRCh37\t{review}\t{sig}\n")


def write_snpedia_tsv(path, snpedia):
    with open(path, "w") as fh:
        for rsid, mag in sorted(snpedia.items()):
            fh.write(f"{rsid}\t{mag}\n")


def write_gnomad_vcf(path, coords, afs):
    with open(path, "w") as fh:
        fh.write("##fileformat=VCFv4.2\n")
        fh.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
        for rsid, af in sorted(afs.items()):
            chrom, pos, ref, alt = coords[rsid]
            fh.write(f"{chrom}\t{pos}\t{rsid}\t{ref}\t{alt}\t.\tPASS\tAF={af}\n")


# --------------------------------------------------------------------------- #
# full-set downloader
# --------------------------------------------------------------------------- #

def download_full(name, url, cache, email):
    dest = os.path.join(cache, os.path.basename(urllib.parse.urlparse(url).path))
    headers = {"User-Agent": f"snp-insights/0.1 ({email or 'no-contact'})"}
    req = urllib.request.Request(url, headers=headers)
    print(f"  {name}: {url}")
    with urllib.request.urlopen(req, timeout=300) as resp, open(dest, "wb") as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
    return dest


def main():
    ap = argparse.ArgumentParser(description="Fetch reference data into a local cache.")
    ap.add_argument("--targets", action="append", default=[], help="targets JSON (small mode); repeatable")
    ap.add_argument("--full", action="store_true", help="download complete files instead of per-record")
    ap.add_argument("--cache", default=os.path.expanduser("~/.cache/snp-insights"))
    ap.add_argument("--email", default=os.environ.get("SNP_INSIGHTS_EMAIL"),
                    help="contact email for NCBI politeness (or env SNP_INSIGHTS_EMAIL)")
    ap.add_argument("--accept-license", action="store_true", help="acknowledge SNPedia CC BY-NC-SA (non-commercial)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    ap.add_argument("--no-gwas", action="store_true", help="small mode: skip the GWAS full-file download")
    ap.add_argument("--sizes", action="store_true", help="HEAD the --full URLs, print sizes, and exit")
    ap.add_argument("--yes", action="store_true", help="allow a >5 GB --full download")
    args = ap.parse_args()

    if args.sizes:
        print("full-file sizes (Content-Length):")
        for name, url in FULL_URLS.items():
            try:
                n = head_size(url, args.email)
            except Exception as exc:  # noqa: BLE001
                print(f"  {name}: {exc}")
                continue
            print(f"  {name}: {n / 1_000_000_000:.2f} GB" if n else f"  {name}: size unknown")
        return 0

    if args.full:
        plan = [("clinvar", FULL_URLS["clinvar"]), ("dbsnp", FULL_URLS["dbsnp"]),
                ("rsmerge", FULL_URLS["rsmerge"]), ("gnomad", FULL_URLS["gnomad"]),
                ("gwas", FULL_URLS["gwas"])]
        if args.dry_run:
            print("FULL mode — would download:")
            for name, url in plan:
                print(f"  {name}: {url}")
            return 0
        os.makedirs(args.cache, exist_ok=True)
        sizes, total = {}, 0
        for name, url in plan:
            try:
                s = head_size(url, args.email)
            except Exception:  # noqa: BLE001
                s = None
            sizes[name] = s
            if s:
                total += s
        print("planned downloads:")
        for name, url in plan:
            print(f"  {name}: {sizes[name] / 1_000_000_000:.2f} GB" if sizes[name] else f"  {name}: size unknown")
        print(f"  total: {total / 1_000_000_000:.2f} GB")
        if total > 5_000_000_000 and not args.yes:
            print("Refusing to download >5 GB without --yes.", file=sys.stderr)
            return 1
        manifest = {"mode": "full", "generated_at": now(), "files": {}}
        for name, url in plan:
            try:
                dest = download_full(name, url, args.cache, args.email)
                manifest["files"][name] = {"url": url, "path": dest, "bytes": os.path.getsize(dest),
                                           "sha256": sha256_file(dest)}
                if name == "gwas" and dest.endswith(".zip"):
                    with zipfile.ZipFile(dest) as z:
                        member = next((n for n in z.namelist() if n.endswith(".tsv")), None)
                        if member:
                            z.extract(member, args.cache)
                            manifest["files"]["gwas_tsv"] = {"path": os.path.join(args.cache, member)}
            except Exception as exc:  # noqa: BLE001
                print(f"  {name}: FAILED {exc}", file=sys.stderr)
                manifest["files"][name] = {"url": url, "error": str(exc)}
        with open(os.path.join(args.cache, "manifest.json"), "w") as fh:
            json.dump(manifest, fh, indent=2)
        print(f"wrote manifest.json in {args.cache}")
        return 0

    if not args.targets:
        print("error: small mode needs --targets (or use --full)", file=sys.stderr)
        return 2
    rsids = load_target_rsids(args.targets)
    snpedia_on = args.accept_license
    plan = {
        "rsids": rsids,
        "sources": ["dbsnp (NCBI variation API)", "clinvar (E-utilities)",
                    "gnomad (GraphQL, via dbSNP coordinates)"]
                   + ([] if args.no_gwas else ["gwas (full file, filtered locally)"])
                   + (["snpedia (MediaWiki API)"] if snpedia_on else []),
        "note": "GWAS has no per-rsID API; its zip (~70 MB) is downloaded and filtered.",
    }
    if args.dry_run:
        print(f"SMALL mode: {len(rsids)} rsIDs")
        for r in rsids:
            print(f"  {r}")
        print("would query:")
        for s in plan["sources"]:
            print(f"  {s}")
        print(plan["note"])
        return 0

    os.makedirs(args.cache, exist_ok=True)
    print(f"fetching {len(rsids)} rsIDs into {args.cache}")
    manifest = {"mode": "small", "generated_at": now(), "rsid_count": len(rsids), "files": {}}

    coords = fetch_dbsnp_small(rsids, args.email)
    write_dbsnp_tsv(os.path.join(args.cache, "dbsnp.tsv"), coords)
    manifest["files"]["dbsnp"] = {"path": "dbsnp.tsv", "records": len(coords)}

    clinvar = fetch_clinvar_small(rsids, args.email)
    write_clinvar_tsv(os.path.join(args.cache, "clinvar.tsv"), clinvar)
    manifest["files"]["clinvar"] = {"path": "clinvar.tsv", "records": len(clinvar)}

    afs = fetch_gnomad_small(coords, args.email)
    write_gnomad_vcf(os.path.join(args.cache, "gnomad.small.vcf"), coords, afs)
    manifest["files"]["gnomad"] = {"path": "gnomad.small.vcf", "records": len(afs)}

    if not args.no_gwas:
        print("  downloading GWAS zip and filtering ...")
        try:
            n = fetch_gwas_small(set(rsids), args.email, args.cache)
            manifest["files"]["gwas"] = {"path": "gwas.tsv", "records": n}
        except Exception as exc:  # noqa: BLE001
            print(f"  gwas: {exc}", file=sys.stderr)

    if snpedia_on:
        snpedia = fetch_snpedia_small(rsids, args.email)
        write_snpedia_tsv(os.path.join(args.cache, "snpedia.tsv"), snpedia)
        manifest["files"]["snpedia"] = {"path": "snpedia.tsv", "records": len(snpedia)}

    with open(os.path.join(args.cache, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    print(f"wrote {args.cache}/{{dbsnp.tsv,clinvar.tsv,gnomad.small.vcf}} + manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
