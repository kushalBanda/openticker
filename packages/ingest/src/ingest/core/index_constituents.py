import csv
import io

import httpx

from ingest.core.constants import (
    KNOWN_INDICES,
    NSE_INDEX_CSV_URLS,
    NSE_USER_AGENT,
    NSE_WARMUP_URL,
)


async def fetch_index_constituents(index_name: str) -> list[str]:
    """Fetch an NSE index's current constituent symbols.

    NSE only serves this CSV to requests that look like a browser and
    carry cookies from a prior visit to nseindia.com, so this warms up a
    session before requesting the CSV itself.

    Raises:
        ValueError: If index_name is not a known index.
        httpx.HTTPStatusError: If NSE returns a non-2xx response.
    """
    if index_name not in KNOWN_INDICES:
        raise ValueError(f"unknown index_name: {index_name!r}")

    headers = {"User-Agent": NSE_USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    async with httpx.AsyncClient(headers=headers, timeout=10.0) as client:
        await client.get(NSE_WARMUP_URL)
        response = await client.get(NSE_INDEX_CSV_URLS[index_name])
        response.raise_for_status()

    reader = csv.DictReader(io.StringIO(response.text))
    return [row["Symbol"].strip() for row in reader if row.get("Symbol")]
