"""Live FX rates — refresh static currency rates from open.er-api.com.

Enabled with FETCH_FX_RATES=1. Results are cached locally for a day so the
app stays fully offline-friendly between refreshes (and if the fetch fails,
the previously configured static rates keep working).
"""
import json
import os
import time
from datetime import datetime, timezone
from urllib.request import urlopen

from .config import FX_API_URL as API_URL
from .config import FX_CACHE_TTL_SECONDS as CACHE_TTL
from .config import FX_FETCH_TIMEOUT_SECONDS as FETCH_TIMEOUT


def _read_cache(path, base, ttl=None):
    ttl = CACHE_TTL if ttl is None else ttl
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if (data.get("base") == base
                and time.time() - float(data.get("ts", 0)) < ttl
                and isinstance(data.get("rates"), dict)):
            return data["rates"]
    except (OSError, ValueError, TypeError):
        pass
    return None


def _write_cache(path, base, rates):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"base": base, "ts": time.time(), "rates": rates}, f)
    except OSError:
        pass


def _fetch(base, timeout=None, api_url=None):
    timeout = FETCH_TIMEOUT if timeout is None else timeout
    api_url = API_URL if api_url is None else api_url
    with urlopen(api_url.format(base=base), timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    rates = data.get("rates") or {}
    # The API reports how much of each currency equals 1 unit of the base;
    # our rates are the inverse (how much base equals 1 unit of the currency).
    return {str(k).upper(): round(1.0 / float(v), 6)
            for k, v in rates.items()
            if isinstance(v, (int, float)) and v > 0}


def refresh_rates(config, force=False):
    """Update config CURRENCY_RATES/CURRENCY_CODES from cache or API.

    Returns a dict describing what happened (or None when disabled/failed).
    Never raises — a failed refresh simply keeps the current rates.
    """
    if not config.get("FX_AUTO_FETCH"):
        return None
    base = (config.get("BASE_CURRENCY") or "INR").upper()
    cache = config.get("FX_CACHE_FILE")
    ttl = config.get("FX_CACHE_TTL_SECONDS", CACHE_TTL) or CACHE_TTL
    rates = None if force else _read_cache(cache, base, ttl)
    source = "cache"
    if rates is None:
        try:
            rates = _fetch(base, config.get("FX_FETCH_TIMEOUT_SECONDS",
                                            FETCH_TIMEOUT),
                           config.get("FX_API_URL", API_URL))
            source = "api"
        except Exception as e:  # noqa: BLE001 — offline is fine
            import logging
            logging.getLogger("exptracker").warning(
                "FX refresh failed (%s) — keeping current rates.", e)
            return None
    rates[base] = 1.0
    # Merge over the configured rates instead of replacing them: a partial
    # API/cache response must never shrink the supported currency set
    # (previously-valid imports would start failing as "Unsupported").
    merged = dict(config.get("CURRENCY_RATES") or {})
    merged.update(rates)
    merged[base] = 1.0
    config["CURRENCY_RATES"] = merged
    config["CURRENCY_CODES"] = sorted(merged)
    if source == "api" and cache:
        _write_cache(cache, base, rates)
    return {"source": source, "base": base,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "currencies": len(rates)}
