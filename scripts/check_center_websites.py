"""Check public catalogue URLs; cache evidence and preserve social links.

Writes resumable JSONL evidence. Only repeated definite failures qualify for
removal; timeouts, TLS problems, bot blocks and server errors remain unresolved.
No account credentials, cookies or application data are sent to these sites.
"""

import argparse
import csv
import json
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests

SOCIAL_HOSTS = {"facebook.com", "fb.com", "fb.me", "instagram.com", "instagr.am", "twitter.com", "x.com",
                "tiktok.com", "youtube.com", "youtu.be", "linkedin.com", "vk.com", "weibo.com",
                "wechat.com", "weixin.qq.com", "wa.me", "whatsapp.com", "line.me", "linktr.ee", "threads.net",
                "pinterest.com", "tripadvisor.com", "t.me", "telegram.me", "m.me", "messenger.com"}
LOCAL = threading.local()


def is_contact(value):
    value = value.strip()
    if re.match(r"^(mailto|tel|sms|smsto|whatsapp|skype|tg|line|viber|weixin):", value, re.I):
        return True
    return bool(re.fullmatch(r"[^\s@/:]+@[^\s@/:]+\.[^\s@/:]+", value))


def is_social(url):
    host = (urlsplit(url if "://" in url else "//" + url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in SOCIAL_HOSTS)


def normalize(url):
    url = url.strip()
    url = re.sub(r"^(https?://):+(?=www\.)", r"\1", url, flags=re.I)
    return url if "://" in url else "https://" + url


def parked_page(url, body):
    host = (urlsplit(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in
           ("sedoparking.com", "hugedomains.com", "dan.com", "afternic.com", "ww1.domainparking.com")):
        return "redirect_to_domain_sales_or_parking"
    if host in {"expireddomains.com", "www.expireddomains.com", "buydomains.com", "www.buydomains.com"}:
        return "redirect_to_expired_domain_sales"
    path = urlsplit(url).path.lower()
    if (host.endswith("godaddy.com") and path.startswith("/forsale") or
            host in {"sedo.com", "www.sedo.com"} and path.startswith("/search/details") or
            host in {"domainmarket.com", "www.domainmarket.com"} and path.startswith("/buynow")):
        return "redirect_to_domain_sales_listing"
    title = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    title = re.sub(r"\s+", " ", title[1]).lower() if title else ""
    if any(s in title for s in ("domain is for sale", "domain for sale", "buy this domain", "domain expired",
                                "account suspended", "website has been suspended", "this website is for sale")):
        return "expired_suspended_or_for_sale_title"
    if "sedoparking.com/" in body and ("buy this domain" in body.lower() or "domain is for sale" in body.lower()):
        return "domain_parking_page"
    return None


def attempt(url):
    if not hasattr(LOCAL, "session"):
        LOCAL.session = requests.Session()
        LOCAL.session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; PelagiaCatalogLinkCheck/1.0)",
                                      "Accept": "text/html,application/xhtml+xml,*/*;q=0.5"})
    try:
        with LOCAL.session.get(url, timeout=(5, 10), allow_redirects=True, stream=True) as response:
            # A tiny bounded prefix suffices for generic parking/error pages.
            content = response.raw.read(16384, decode_content=True)
            body = content.decode(response.encoding or "utf-8", errors="replace")
            result = {"url": url, "status": response.status_code, "final_url": response.url}
            if is_social(response.url):
                result["outcome"] = "social_preserved"
            elif "cloudways-static-content.s3.us-east-1.amazonaws.com/error_page/maintenance-domain-mapping.html" in body:
                result["outcome"] = "dead_hosting"
                result["detail"] = "hosting_domain_mapping_error"
            elif 200 <= response.status_code < 400:
                parked = parked_page(response.url, body)
                result["outcome"] = "dead_parked" if parked else "live"
                if parked:
                    result["detail"] = parked
            elif response.status_code in {404, 410}:
                result["outcome"] = "dead_http"
            else:
                result["outcome"] = "unresolved_http"
            return result
    except requests.exceptions.SSLError:
        return {"url": url, "outcome": "unresolved_tls"}
    except requests.exceptions.Timeout:
        return {"url": url, "outcome": "unresolved_timeout"}
    except requests.exceptions.ConnectionError as error:
        message = str(error)
        dns = any(s in message for s in ("NameResolutionError", "nodename nor servname", "Name or service not known"))
        return {"url": url, "outcome": "dead_dns" if dns else "unresolved_connection", "detail": message[:300]}
    except (requests.exceptions.RequestException, ValueError, UnicodeError, OSError) as error:
        return {"url": url, "outcome": "unresolved_error", "detail": str(error)[:300]}


def check(url, retry=False):
    if is_contact(url):
        return {"website": url, "classification": "contact_preserved", "attempts": []}
    if is_social(url):
        return {"website": url, "classification": "social_preserved", "attempts": []}
    normalized = normalize(url)
    parts = urlsplit(normalized)
    if parts.scheme not in {"http", "https"} or not parts.hostname or "." not in parts.hostname:
        return {"website": url, "classification": "dead_invalid_url", "attempts": []}
    variants = [normalized]
    if retry:
        # A dead deep link does not establish that the business's homepage is
        # dead. Evidence records a working alternative so the CSV can repair it.
        other_scheme = "https" if parts.scheme == "http" else "http"
        variants.append(urlunsplit((other_scheme, parts.netloc, parts.path, parts.query, "")))
        alternate_host = parts.netloc[4:] if parts.netloc.lower().startswith("www.") else "www." + parts.netloc
        variants.append(urlunsplit(("https", alternate_host, parts.path, parts.query, "")))
        if parts.path and parts.path != "/":
            variants.append(urlunsplit(("https", parts.netloc, "/", "", "")))
    attempts = []
    for variant in dict.fromkeys(variants):
        result = attempt(variant)
        attempts.append(result)
        if result["outcome"] in {"live", "social_preserved"}:
            return {"website": url, "classification": result["outcome"], "working_url": variant, "attempts": attempts}
        if result["outcome"] == "unresolved_http" and result.get("status") in {401, 403, 429, 451}:
            return {"website": url, "classification": "unresolved", "attempts": attempts}
        if retry and result["outcome"] == "dead_dns" and len(attempts) == 1:
            alternate = parts.hostname[4:] if parts.hostname.startswith("www.") else "www." + parts.hostname
            return confirm_dns({"website": url, "classification": "dead_confirmed", "attempts": attempts,
                                "dns_hosts": [parts.hostname, alternate]})
        if retry and len(attempts) >= 2 and all(a["outcome"] in
                {"unresolved_timeout", "unresolved_connection", "unresolved_error"} for a in attempts):
            return {"website": url, "classification": "unresolved", "attempts": attempts}
    outcomes = {result["outcome"] for result in attempts}
    definite = {"dead_http", "dead_dns", "dead_parked", "dead_hosting"}
    confirmed = outcomes <= definite or ("dead_hosting" in outcomes and outcomes <= definite | {"unresolved_tls"})
    classification = "dead_confirmed" if retry and confirmed else "needs_retry" if not retry else "unresolved"
    return {"website": url, "classification": classification, "attempts": attempts}


def confirm_dns(record):
    """Require independent NXDOMAIN evidence before deleting DNS failures."""
    confirmations = {}
    for host in sorted(set(record.get("dns_hosts") or [urlsplit(a["url"]).hostname for a in record["attempts"]])):
        status = None
        for endpoint in ("https://dns.google/resolve", "https://cloudflare-dns.com/dns-query"):
            try:
                response = requests.get(endpoint, params={"name": host, "type": "A"},
                                        headers={"Accept": "application/dns-json"}, timeout=8)
                response.raise_for_status()
                status = response.json().get("Status")
                break
            except (requests.exceptions.RequestException, ValueError):
                continue
        confirmations[host] = status
    result = dict(record)
    result["dns_confirmation"] = confirmations
    if not confirmations or any(status != 3 for status in confirmations.values()):
        result["classification"] = "unresolved"
    return result


def read_evidence(path):
    """A later timeout does not erase an earlier conclusive result this run."""
    cached = {}
    if not path.exists():
        return cached
    terminal = {"live", "social_preserved", "contact_preserved", "dead_confirmed"}
    explicit_failures = Counter()
    for line in path.read_text().splitlines():
        record = json.loads(line)
        explicit_failures[record["website"]] += sum(
            attempt.get("outcome") in {"dead_parked", "dead_hosting"} or
            bool(parked_page(attempt.get("final_url", ""), ""))
            for attempt in record.get("attempts", []))
        if record["classification"] == "live" and any(parked_page(a.get("final_url", ""), "")
                for a in record.get("attempts", []) if a.get("final_url")):
            record["classification"] = "needs_retry"
        if record.get("retry_completed") and record["classification"] in {"needs_retry", "unresolved"} and explicit_failures[record["website"]] >= 2:
            record["classification"] = "dead_confirmed"
            record["confirmation"] = "repeated_explicit_parking_or_hosting_failure"
        previous = cached.get(record["website"])
        if previous and previous["classification"] in terminal and record["classification"] in {"needs_retry", "unresolved"}:
            # Independent DNS can overturn a local lookup failure.
            if not record.get("dns_confirmation"):
                continue
        cached[record["website"]] = record
    return cached


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=Path("data/padi_dive_centers.csv"))
    parser.add_argument("--evidence", type=Path, default=Path("output/center-cleanup/website_checks.jsonl"))
    parser.add_argument("--workers", type=int, default=64)
    parser.add_argument("--retry", action="store_true")
    parser.add_argument("--confirm-dns", action="store_true")
    args = parser.parse_args()
    with args.csv.open(encoding="utf-8-sig") as handle:
        urls = sorted({row["website"].strip() for row in csv.DictReader(handle)
                       if row["website"].strip() and row["physical_address"].strip()})
    cached = read_evidence(args.evidence)
    selected = [url for url in urls if (url not in cached if not args.retry else
                cached.get(url, {}).get("classification") == "needs_retry" or
                cached.get(url, {}).get("classification") == "unresolved" and not cached[url].get("attempts") or
                cached.get(url, {}).get("classification") == "dead_invalid_url" and "http://:" in url)]
    if args.confirm_dns:
        selected = [url for url, record in cached.items()
                    if record["classification"] == "dead_confirmed" and not record.get("dns_confirmation")
                    and record.get("attempts") and all(a["outcome"] == "dead_dns" for a in record["attempts"])]
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"distinct_urls": len(urls), "selected": len(selected), "retry": args.retry}), flush=True)
    counts = Counter()
    with args.evidence.open("a") as handle, ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {(pool.submit(confirm_dns, cached[url]) if args.confirm_dns else
                    pool.submit(check, url, args.retry)): url for url in selected}
        for index, future in enumerate(as_completed(futures), 1):
            try:
                result = future.result()
            except Exception as error:
                result = {"website": futures[future], "classification": "unresolved", "error": str(error)[:300]}
            result["checked_at"] = datetime.now(timezone.utc).isoformat()
            result["retry_completed"] = args.retry
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
            handle.flush()
            counts[result["classification"]] += 1
            if index % 250 == 0 or index == len(selected):
                print(json.dumps({"completed": index, "total": len(selected), "results": counts}), flush=True)


if __name__ == "__main__":
    main()
