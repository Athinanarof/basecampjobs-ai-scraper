import os
import hashlib
import logging
from typing import List
from azure.data.tables import TableServiceClient
from azure.core.exceptions import ResourceNotFoundError

CACHE_TABLE = "JobUrlCache"


def _table_client():
    service = TableServiceClient.from_connection_string(
        os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    )
    service.create_table_if_not_exists(CACHE_TABLE)
    return service.get_table_client(CACHE_TABLE)


def filter_new(urls: List[str]) -> List[str]:
    client = _table_client()
    new: List[str] = []
    for url in urls:
        try:
            client.get_entity(partition_key="url", row_key=_key(url))
        except ResourceNotFoundError:
            new.append(url)
        except Exception as e:
            logging.warning(f"Cache read error for {url[:60]}: {e}")
            new.append(url)
    return new


def mark_seen(urls: List[str]) -> None:
    client = _table_client()
    for url in urls:
        try:
            client.upsert_entity({
                "PartitionKey": "url",
                "RowKey": _key(url),
                "url": url,
            })
        except Exception as e:
            logging.warning(f"Cache write error for {url[:60]}: {e}")


def _key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:32]
