#!/usr/bin/env python3
"""Count Nature Aging publications per author, split by position.

Queries PubMed via NCBI E-utilities for every paper in the Nature Aging
journal (NLM abbreviation `Nat Aging`), parses the author lists, and
reports the top authors as (a) first author, (b) last author, and (c) any
authorship position.

Usage:
    python3 nature_aging_authors.py [--email you@example.com] [--top 25]

Set NCBI_API_KEY in the environment to raise the rate limit from 3 to 10
requests/second.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
JOURNAL_QUERY = '"Nat Aging"[Journal]'


def _get(url: str, params: dict) -> bytes:
    api_key = os.environ.get("NCBI_API_KEY")
    if api_key:
        params = {**params, "api_key": api_key}
    full = f"{url}?{urlencode(params)}"
    req = Request(full, headers={"User-Agent": "nataging-stats/1.0"})
    with urlopen(req, timeout=60) as resp:
        return resp.read()


def search_all_pmids() -> list[str]:
    pmids: list[str] = []
    retmax = 10000
    retstart = 0
    while True:
        data = _get(
            f"{EUTILS}/esearch.fcgi",
            {
                "db": "pubmed",
                "term": JOURNAL_QUERY,
                "retmode": "json",
                "retmax": retmax,
                "retstart": retstart,
            },
        )
        import json
        payload = json.loads(data)["esearchresult"]
        total = int(payload["count"])
        batch = payload.get("idlist", [])
        pmids.extend(batch)
        retstart += len(batch)
        if retstart >= total or not batch:
            break
        time.sleep(0.12)
    return pmids


def fetch_records(pmids: Iterable[str], batch: int = 200) -> Iterable[ET.Element]:
    pmid_list = list(pmids)
    for i in range(0, len(pmid_list), batch):
        chunk = pmid_list[i : i + batch]
        data = _get(
            f"{EUTILS}/efetch.fcgi",
            {"db": "pubmed", "id": ",".join(chunk), "retmode": "xml"},
        )
        root = ET.fromstring(data)
        for article in root.findall(".//PubmedArticle"):
            yield article
        time.sleep(0.12)


def author_key(author: ET.Element) -> str | None:
    collective = author.findtext("CollectiveName")
    if collective:
        return collective.strip()
    last = (author.findtext("LastName") or "").strip()
    if not last:
        return None
    initials = (author.findtext("Initials") or "").strip()
    fore = (author.findtext("ForeName") or "").strip()
    if initials:
        return f"{last} {initials}"
    if fore:
        return f"{last} {fore[:1]}"
    return last


def tally(articles: Iterable[ET.Element]):
    any_pos: Counter[str] = Counter()
    first: Counter[str] = Counter()
    last: Counter[str] = Counter()
    article_types: Counter[str] = Counter()
    n_articles = 0
    for art in articles:
        n_articles += 1
        for pt in art.findall(".//PublicationType"):
            if pt.text:
                article_types[pt.text] += 1
        authors = art.findall(".//AuthorList/Author")
        if not authors:
            continue
        names: list[str] = []
        for a in authors:
            k = author_key(a)
            if k:
                names.append(k)
        if not names:
            continue
        first[names[0]] += 1
        last[names[-1]] += 1
        for n in set(names):
            any_pos[n] += 1
    return n_articles, any_pos, first, last, article_types


def print_top(title: str, counter: Counter[str], top: int) -> None:
    print(f"\n=== {title} ===")
    width = max((len(n) for n, _ in counter.most_common(top)), default=0)
    for rank, (name, count) in enumerate(counter.most_common(top), 1):
        print(f"{rank:>3}. {name:<{width}}  {count}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=25, help="rows per ranking")
    ap.add_argument("--cache", default="nataging_pubmed.xml",
                    help="cache file for fetched XML records")
    args = ap.parse_args()

    print(f"Searching PubMed for {JOURNAL_QUERY}...", file=sys.stderr)
    pmids = search_all_pmids()
    print(f"Found {len(pmids)} PMIDs.", file=sys.stderr)

    print("Fetching author records...", file=sys.stderr)
    articles = list(fetch_records(pmids))
    print(f"Fetched {len(articles)} articles.", file=sys.stderr)

    n, any_pos, first, last, ptypes = tally(articles)
    print(f"\nNature Aging papers analyzed: {n}")
    print(f"Unique authors: {len(any_pos)}")
    print("\nPublication-type breakdown (top 10):")
    for t, c in ptypes.most_common(10):
        print(f"  {t}: {c}")

    print_top("Top authors by ANY position (includes middle authors)",
              any_pos, args.top)
    print_top("Top FIRST authors", first, args.top)
    print_top("Top LAST (senior) authors", last, args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
