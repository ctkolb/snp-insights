# Reference data

This page explains where the knowledge in a report comes from, what each public
source is, and how to get the files if you want to rebuild or extend the panel.
If you only want to run v0.1.0 on a raw file, you can skip all of it: see
[getting-started.md](getting-started.md).

Nothing here is medical advice.

## Why reference data exists

Your raw file holds only rsIDs (marker names) and the letters you carry. It says
nothing about what a marker means. That knowledge lives in public databases that
researchers and clinical labs maintain. In this project those databases are called
**reference data**.

The pipeline copies the small part it needs into a **panel**: a snapshot file that
holds, for each curated marker, its position, the effect allele, the evidence
and the population frequency. This copying step is called the ETL (extract,
transform, load) and is done by `build-panel`.

The rule that matters: **annotation never touches the network.** `annotate`,
`narrate`, `run` and `check-raw` read your raw file and a panel file, and nothing
else. Only `fetch` talks to the internet, and only when you run it yourself.

## The sources

Terms (verify the current terms of each source; not legal advice): ClinVar and
dbSNP are public domain (NCBI; identify yourself and be polite). gnomAD is free,
and some datasets carry extra terms. The GWAS Catalog is free (EMBL-EBI). SNPedia
is CC BY-NC-SA 3.0, which is non-commercial; it is a user-supplied file only and
is never auto-fetched or redistributed. OMIM is not downloaded (link-only).

| Source | What it is | What this project uses it for | Fetched automatically? |
| --- | --- | --- | --- |
| **dbSNP** (NCBI) | The catalog of known variants and their rsIDs. | Coordinates and alleles on GRCh37 (the genome build the panel uses). Its RsMergeArch file maps retired rsIDs to current ones so an older ID in a file still matches. | Yes: the variation API (small fetch) or the full VCF (`fetch --full`). |
| **ClinVar** (NCBI) | A public archive of reports on how variants relate to health conditions, with a review level shown as stars. | The clinical significance and review stars for the health entries (carrier and risk). | Yes: `variant_summary` is downloaded by default (about 0.5 GB, once); `--clinvar-mode api` uses the lighter E-utilities instead. |
| **gnomAD** (Broad Institute) | Allele frequencies from a large set of sequenced people. | How common the effect allele is in the population. | Yes: the GraphQL API (small fetch) or the full VCF (`fetch --full`). |
| **GWAS Catalog** (EMBL-EBI), via **Open Targets** or the full file | A catalog of published genome-wide association studies. | Counting matching studies for trait entries. v0.1.0 has no trait entries. | Yes: Open Targets per rsID by default (`--gwas-mode ot`, no big download), or the full associations zip with `--gwas-mode full` (about 70 MB). |
| **SNPedia** | A community wiki that scores variants by "magnitude" (noteworthiness). | An optional extra score. | No. Its site blocks programmatic access. See [SNPedia (manual)](#snpedia-manual). |
| **OMIM** | A catalog of genes and genetic conditions. | Link-only: each finding links to an OMIM search. | No. |
| **MedlinePlus Genetics** and **GeneReviews** | Plain-language and clinician-written gene summaries. | Link-only: the report's "Read more" lines link to them; the code writes the links, never the model. | No. |

## Do you need to fetch anything?

| What you want to do | Fetch needed? |
| --- | --- |
| Run v0.1.0 on your own file | **No.** The built release panel, `data/targets.release-panel.json`, is already in the repository. |
| Try the tool on synthetic data | No. |
| Rebuild `data/panel.sample.json` from the tiny samples | No. See [The synthetic samples](#the-synthetic-samples). |
| Rebuild or extend the release panel, or add variants | Yes, by one of the three ways below. |

The three ways to get real reference data:

| Way | What it does | Size | Privacy trade-off |
| --- | --- | --- | --- |
| **Small fetch** (`fetch --targets ...`, the default) | Looks up only the rsIDs listed in your targets files. | ClinVar `variant_summary` is about 0.5 GB, downloaded once, by default. `--clinvar-mode api` avoids it. The GWAS zip with `--gwas-mode full` is about 70 MB. | Each source that is queried per record learns which variants you asked about (an interest signal), never your genotype. A plain file download, such as the ClinVar one, reveals nothing selective. |
| **`fetch --full`** | Downloads the complete official files (ClinVar, dbSNP, RsMergeArch, gnomAD, GWAS Catalog) into the cache. | dbSNP plus gnomAD alone are about 90 GB. It refuses to pull more than 5 GB without `--yes`. `--sizes` shows the real sizes first. | Nothing selective is revealed: every source sees a plain file download. |
| **Manual download** | You download the same files in a browser. See [Manual full-file downloads](#manual-full-file-downloads). | Same files as `--full`. | Same as `--full`. |

Never derive the fetch list from your own raw file: that would tell the sources
what you carry. The targets files are curated lists, not your coverage.

These commands use the network (except `--dry-run`, which prints the plan and
exits). Run them yourself; this project's tests never do:

```bash
# see exactly what would be fetched
python -m snp_insights fetch --targets data/targets.carrier.json --dry-run

# fetch only the records the targets need (the default)
python -m snp_insights fetch --targets data/targets.carrier.json --email you@example.com

# or download the complete official files
python -m snp_insights fetch --full --email you@example.com
```

`fetch` takes no raw-file argument. `--email` is optional; if you give one, it is
sent to the sources in the User-Agent header so NCBI can contact you.

## What fetch writes (the cache)

`fetch` writes into a cache directory, `~/.cache/snp-insights` by default (change
it with `--cache`). The cache is outside the repository on purpose.

A **small fetch** writes:

- `dbsnp.tsv`: coordinates and alleles for your rsIDs.
- `clinvar.tsv`: the chosen ClinVar record per rsID.
- `gnomad.small.vcf`: allele frequencies.
- `gwas.tsv`: GWAS study counts (not written with `--no-gwas`).
- `manifest.json`: the run mode, the time, the rsID count, and a record count per file.

With the default `--clinvar-mode summary` it also leaves the downloaded
`variant_summary.txt.gz` in the cache, and with `--gwas-mode full` the GWAS zip.

A **`fetch --full`** writes the complete files under the names they have at the
source:

- `variant_summary.txt.gz` (ClinVar)
- `GCF_000001405.25.gz` (dbSNP, GRCh37 VCF)
- `RsMergeArch.bcp.gz` (dbSNP merge history)
- `gnomad.exomes.r2.1.1.sites.vcf.bgz` (gnomAD)
- `gwas-catalog-associations_ontology-annotated-full.zip` (GWAS Catalog), plus the
  `.tsv` file it extracts from the zip
- `manifest.json`: for each file, the URL, path, size in bytes and sha256.

A file that is already in the cache and not empty is reused, not downloaded again.

**How `build-panel --cache` uses the cache.** When you pass `--cache DIR`,
`build-panel` fills every source path you left unset by looking in `DIR` for these
names, in this order, and uses the first one that exists:

| Left unset | Looked for in the cache |
| --- | --- |
| `--clinvar` | `clinvar.tsv`, then `variant_summary.txt.gz` |
| `--dbsnp` | `dbsnp.tsv`, then `GCF_000001405.25.gz` |
| `--gnomad` | `gnomad.small.vcf`, then `gnomad.exomes.r2.1.1.sites.vcf.bgz` |
| `--gwas` | `gwas.tsv`, then `gwas-catalog-download-associations-alt-full.tsv` |
| `--snpedia` | `snpedia.tsv` (`fetch` never writes it; put it there yourself) |
| `--dbsnp-merge` | `RsMergeArch.bcp.gz` |

A path you pass explicitly always wins. If the `.tsv` that came out of the GWAS zip
has a different name from the one above, pass it with `--gwas`.

## Flags for fetch

These are all the flags in `fetch --help`.

| Flag | What it does |
| --- | --- |
| `--targets` | A targets JSON file (small mode). Repeat it to use several. The rsIDs in these files are the small set. |
| `--full` | Download the complete files instead of per-record lookups. |
| `--cache` | The cache directory (default `~/.cache/snp-insights`). |
| `--email` | A contact address for NCBI politeness, or set the environment variable `SNP_INSIGHTS_EMAIL`. Optional. |
| `--accept-license` | Acknowledge the SNPedia license. SNPedia is still not downloaded; the command prints the manual steps. |
| `--dry-run` | Print the plan and exit. |
| `--no-gwas` | Small mode: skip the GWAS step. |
| `--gwas-mode` | Small mode: `ot` (Open Targets per rsID, no big download) or `full` (download the GWAS Catalog zip and filter it). |
| `--clinvar-mode` | Small mode: `summary` (download `variant_summary`; it matches the record to the curated condition) or `api` (E-utilities; lighter, no condition match). |
| `--sizes` | Ask each full-file URL for its size, print it, and exit. |
| `--yes` | Allow a `--full` download of more than 5 GB. |

## Flags for build-panel

`build-panel` joins a targets file with the reference files and writes a panel.
Without `--out` it prints the panel JSON to stdout. These are all the flags in
`build-panel --help`. Files can be plain or `.gz`.

| Flag | What goes there |
| --- | --- |
| `--targets` | The curated targets file (required). |
| `--clinvar` | ClinVar: `variant_summary.txt.gz` or a normalized TSV. |
| `--gnomad` | A gnomAD VCF (GRCh37). |
| `--dbsnp` | A dbSNP VCF (GRCh37) or a normalized TSV; fills coordinates and alleles. |
| `--gwas` | A GWAS Catalog associations TSV; drives the trait association tier. |
| `--snpedia` | A file of `rsid<TAB>magnitude`, or JSON. Optional. |
| `--dbsnp-merge` | The dbSNP RsMergeArch file (old rsID to new rsID). |
| `--curated-evidence` | The curated ClinVar evidence file for release-format targets. |
| `--cache` | A directory from `fetch`; fills the source paths you did not set. |
| `--merge-direction` | Which RsMergeArch column holds the retired rsID: `high-to-low` (default) or `low-to-high`. |
| `--dbsnp-release` | A label recorded in the panel for the dbSNP release. |
| `--clinvar-release` | A label recorded for the ClinVar release. |
| `--gnomad-release` | A label recorded for the gnomAD release. |
| `--gwas-release` | A label recorded for the GWAS Catalog release. |
| `--snpedia-release` | A label recorded for the SNPedia release. |
| `--retrieved-at` | The retrieval time recorded in the panel. |
| `--out` | Where to write the panel (short form `-o`; the default is stdout). |

The five release labels and `--retrieved-at` are only written into the panel's
provenance. They have built-in default values, and `build-panel` does not read the
real release from your files. When you build from real files, set them yourself so
the panel records the truth.

## The synthetic samples

`fixtures/sources/` holds tiny, synthetic (invented) files that imitate each
source. They are only for learning and for the tests; they are not real data and
no report should be built from them.

| File | What it imitates |
| --- | --- |
| `clinvar.sample.tsv` | A ClinVar `variant_summary`-style table. |
| `clinvar.messy.tsv` | A ClinVar table with awkward rows, used to test robustness. |
| `dbsnp.sample.tsv` | A normalized dbSNP table (rsid, chromosome, position, alleles). |
| `dbsnp.sample.vcf` | A dbSNP VCF. |
| `gnomad.sample.vcf` | A gnomAD VCF with allele frequencies. |
| `gnomad.messy.vcf` | A gnomAD VCF with awkward rows, used to test robustness. |
| `gwas.sample.tsv` | A GWAS Catalog associations table. |
| `rsmerge.sample.tsv` | An RsMergeArch-style merge table. |
| `snpedia.sample.tsv` | A SNPedia `rsid<TAB>magnitude` file. |

This build, from the samples, reproduces `data/panel.sample.json` byte for byte:

```bash
OUT=$(mktemp -d)
python -m snp_insights build-panel --targets data/targets.sample.json \
    --clinvar fixtures/sources/clinvar.sample.tsv \
    --gnomad  fixtures/sources/gnomad.sample.vcf \
    -o "$OUT/panel.sample.json"
```

Compare `"$OUT/panel.sample.json"` with `data/panel.sample.json` (for example with
`cmp`). They are identical.

## Manual full-file downloads

If you prefer to download in a browser, these are the landing pages. Each file
goes to the flag shown. You do not have to decompress anything: plain and `.gz`
files are both accepted.

- **ClinVar** `variant_summary.txt.gz`:
  <https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz>
  (`--clinvar`)
- **dbSNP** GRCh37 VCF `GCF_000001405.25.gz` (large):
  <https://ftp.ncbi.nlm.nih.gov/snp/latest_release/VCF/> (`--dbsnp`)
- **dbSNP** `RsMergeArch`: <https://ftp.ncbi.nlm.nih.gov/snp/>
  (`--dbsnp-merge`)
- **gnomAD** VCF, GRCh37: <https://gnomad.broadinstitute.org/downloads>
  (`--gnomad`)
- **GWAS Catalog** associations TSV:
  <https://www.ebi.ac.uk/gwas/docs/file-downloads> (`--gwas`)

Verify the current terms of each source before you use or share anything.

## Release-format targets and the release panel

A targets file that declares `result_type` is in the release format. For a release
format with carrier entries, `build-panel` also needs the curated evidence file:

```bash
python -m snp_insights build-panel --targets data/targets.release.json \
    --curated-evidence data/targets.release-evidence.json --cache <your-cache> \
    -o "$PRIV/panel.json"
```

`--curated-evidence data/targets.release-evidence.json` gives each carrier entry
its curated per-condition ClinVar record instead of the aggregate row. The
command above shows the shape only; it is not the recorded rebuild command and
needs real reference files.

You do not need to rebuild the release panel to run v0.1.0:
`data/targets.release-panel.json` is already built and tracked. A rebuild is
optional, needs the network or the full files, and is mainly for contributors. The
recorded curation method, the exact rebuild command and the evidence behind each
entry are in [docs/panel-curation.md](panel-curation.md); this page does not restate
or change them.

## SNPedia (manual)

SNPedia adds a *noteworthiness* score (magnitude) for variants, including many
traits that ClinVar and the GWAS Catalog do not cover. Its site blocks automated
downloads, so it is not auto-fetched. To include it:

```bash
# WORK is any scratch directory outside the repository
# 1. download SNPedia's data in a browser (its site's Download page)
# 2. convert it to our format (MediaWiki XML export or JSON dump):
python tools/snpedia_to_tsv.py snpedia_dump.xml -o "$WORK/snpedia.tsv"
# 3. build with it:
python -m snp_insights build-panel --targets data/targets.traits.json \
    --snpedia "$WORK/snpedia.tsv" -o "$WORK/panel.traits.json"
```

The converter accepts a MediaWiki XML export, a JSON map of title to wikitext, or
an already-correct `rsid<TAB>magnitude` TSV and passes it through. SNPedia is
CC BY-NC-SA 3.0 (non-commercial); do not redistribute it.

`data/targets.carrier.json` and `data/targets.traits.json` are draft starter sets:
verify the rsID and condition pairings and trim them before building from them.
Then `python -m snp_insights check-raw --panel <panel> <raw>` shows which targets
your array actually covers.
