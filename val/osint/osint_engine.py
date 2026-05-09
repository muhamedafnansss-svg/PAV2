from __future__ import annotations
import asyncio, json, logging, socket, urllib.request, urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List

logger = logging.getLogger("val.osint")


@dataclass
class OsintResult:
    target: str
    type: str
    whois: dict = field(default_factory=dict)
    dns: dict = field(default_factory=dict)
    http: dict = field(default_factory=dict)
    geo: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)

    def to_report(self) -> str:
        lines = [f"OSINT Report: {self.target}\n"]
        if self.whois:
            lines.append("--- WHOIS ---")
            for k, v in list(self.whois.items())[:10]:
                lines.append(f"  {k}: {v}")
        if self.dns:
            lines.append("\n--- DNS ---")
            for rtype, records in self.dns.items():
                lines.append(f"  {rtype}: {', '.join(str(r) for r in records[:5])}")
        if self.http:
            lines.append("\n--- HTTP ---")
            for k, v in self.http.items():
                if v:
                    lines.append(f"  {k}: {v}")
        if self.geo:
            lines.append("\n--- Geolocation ---")
            for k, v in self.geo.items():
                lines.append(f"  {k}: {v}")
        if self.errors:
            lines.append("\n--- Errors ---")
            for e in self.errors:
                lines.append(f"  WARNING: {e}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "target": self.target, "type": self.type,
            "whois": self.whois, "dns": self.dns,
            "http": self.http, "geo": self.geo,
            "errors": self.errors, "report": self.to_report(),
        }


def _extract_domain(target: str) -> str:
    target = target.strip().lower()
    if target.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(target)
        return parsed.netloc or target
    return target


async def _whois_lookup(domain: str) -> dict:
    try:
        import whois
        loop = asyncio.get_event_loop()
        w = await loop.run_in_executor(None, whois.whois, domain)
        result = {}
        for key in ["domain_name", "registrar", "creation_date", "expiration_date",
                    "updated_date", "name_servers", "status", "emails", "country", "org"]:
            val = getattr(w, key, None)
            if val:
                if isinstance(val, list):
                    val = val[0] if len(val) == 1 else [str(v) for v in val[:3]]
                result[key] = str(val)
        return result
    except ImportError:
        return {"error": "python-whois not installed (pip install python-whois)"}
    except Exception as e:
        return {"error": str(e)}


async def _dns_lookup(domain: str) -> dict:
    results: Dict[str, list] = {}
    try:
        import dns.resolver
        loop = asyncio.get_event_loop()
        for rtype in ["A", "AAAA", "MX", "NS", "TXT"]:
            try:
                answers = await loop.run_in_executor(
                    None, lambda r=rtype: dns.resolver.resolve(domain, r, lifetime=5)
                )
                results[rtype] = [str(r) for r in answers]
            except Exception:
                pass
    except ImportError:
        try:
            addrs = socket.getaddrinfo(domain, None)
            results["A"] = list({a[4][0] for a in addrs if "." in a[4][0]})[:5]
            results["AAAA"] = list({a[4][0] for a in addrs if ":" in a[4][0]})[:3]
        except Exception as e:
            results["error"] = str(e)
    return results


async def _http_metadata(target: str) -> dict:
    url = target if target.startswith(("http://", "https://")) else f"https://{target}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; VAL-OSINT/4.0; +passive)"},
            method="HEAD",
        )
        loop = asyncio.get_event_loop()
        def _fetch():
            try:
                with urllib.request.urlopen(req, timeout=8) as resp:
                    hdrs = dict(resp.headers)
                    return {
                        "status_code": resp.status,
                        "final_url": resp.url,
                        "server": hdrs.get("Server", ""),
                        "content_type": hdrs.get("Content-Type", ""),
                        "x_powered_by": hdrs.get("X-Powered-By", ""),
                        "x_frame_options": hdrs.get("X-Frame-Options", ""),
                        "hsts": hdrs.get("Strict-Transport-Security", ""),
                        "csp": (hdrs.get("Content-Security-Policy", "") or "")[:120],
                    }
            except urllib.error.HTTPError as e:
                return {"status_code": e.code, "error": str(e)}
        return await loop.run_in_executor(None, _fetch)
    except Exception as e:
        return {"error": str(e)}


async def _geolocation(ip: str) -> dict:
    try:
        url = f"http://ip-api.com/json/{ip}?fields=status,country,regionName,city,isp,org,as,query"
        req = urllib.request.Request(url, headers={"User-Agent": "VAL-OSINT/4.0"})
        loop = asyncio.get_event_loop()
        def _fetch():
            with urllib.request.urlopen(req, timeout=8) as resp:
                return json.loads(resp.read())
        data = await loop.run_in_executor(None, _fetch)
        if data.get("status") == "success":
            return {k: v for k, v in data.items() if k != "status"}
        return {}
    except Exception:
        return {}


async def gather(target: str) -> OsintResult:
    domain = _extract_domain(target)
    is_ip = all(c.isdigit() or c == "." for c in domain)
    otype = "ip" if is_ip else ("url" if "://" in target else "domain")
    result = OsintResult(target=target, type=otype)
    logger.info("[OSINT] Passive gather: %s (%s)", domain, otype)
    if not is_ip:
        whois_r, dns_r, http_r = await asyncio.gather(
            _whois_lookup(domain), _dns_lookup(domain), _http_metadata(target),
            return_exceptions=True,
        )
        result.whois = whois_r if isinstance(whois_r, dict) else {"error": str(whois_r)}
        result.dns   = dns_r   if isinstance(dns_r,   dict) else {"error": str(dns_r)}
        result.http  = http_r  if isinstance(http_r,  dict) else {"error": str(http_r)}
        a_records = result.dns.get("A", [])
        if a_records:
            result.geo = await _geolocation(a_records[0])
    else:
        result.geo  = await _geolocation(domain)
        result.http = await _http_metadata(f"http://{domain}")
    logger.info("[OSINT] Complete: %s", domain)
    return result