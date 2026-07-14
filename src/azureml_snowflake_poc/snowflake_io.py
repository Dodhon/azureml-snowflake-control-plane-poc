"""Snowflake reads and authentication from Azure ML compute."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

import pandas as pd

from azureml_snowflake_poc.configuration import ConfigurationError, require

_READ_QUERY = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE | re.DOTALL)


def validate_read_query(query: str) -> str:
    """Accept one read-only query and reject obvious multi-statement configuration errors."""
    normalized = query.strip().rstrip(";").strip()
    if not _READ_QUERY.match(normalized) or ";" in normalized:
        raise ConfigurationError("Snowflake pull query must be one SELECT or WITH statement")
    return normalized


def _oauth_token(config: Mapping[str, Any]) -> str:
    from azure.identity import DefaultAzureCredential

    scope = require(config, "snowflake.oauth_scope")
    return DefaultAzureCredential().get_token(scope).token


def _private_key(config: Mapping[str, Any]) -> bytes:
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient
    from cryptography.hazmat.primitives import serialization

    vault_url = require(config, "snowflake.key_vault_url")
    key_secret_name = require(config, "snowflake.private_key_secret_name")
    secret_client = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())
    key_pem = secret_client.get_secret(key_secret_name).value
    if not key_pem:
        raise ConfigurationError("Snowflake private-key secret is empty")

    passphrase_name = config.get("snowflake", {}).get("private_key_passphrase_secret_name")
    passphrase: bytes | None = None
    if isinstance(passphrase_name, str) and passphrase_name:
        passphrase_value = secret_client.get_secret(passphrase_name).value
        passphrase = passphrase_value.encode() if passphrase_value else None
    key = serialization.load_pem_private_key(key_pem.encode(), password=passphrase)
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def connect(config: Mapping[str, Any]) -> Any:
    """Open a Snowflake connection using External OAuth or Key Vault key pair."""
    import snowflake.connector

    common = {
        "account": require(config, "snowflake.account"),
        "user": require(config, "snowflake.user"),
        "role": require(config, "snowflake.role"),
        "warehouse": require(config, "snowflake.warehouse"),
        "database": require(config, "snowflake.database"),
        "schema": require(config, "snowflake.schema"),
        "application": "azureml_snowflake_control_plane_poc",
    }
    auth_mode = require(config, "snowflake.auth_mode")
    if auth_mode == "external_oauth":
        return snowflake.connector.connect(
            **common,
            authenticator="oauth",
            token=_oauth_token(config),
        )
    if auth_mode == "key_pair":
        return snowflake.connector.connect(**common, private_key=_private_key(config))
    raise ConfigurationError("snowflake.auth_mode must be external_oauth or key_pair")


def fetch_dataframe(
    connection: Any,
    query: str,
    *,
    query_tag: Mapping[str, str],
    parameters: Mapping[str, object] | None = None,
) -> pd.DataFrame:
    """Execute one parameterized, tagged read and return a pandas snapshot."""
    safe_query = validate_read_query(query)
    tag = json.dumps(dict(sorted(query_tag.items())), separators=(",", ":"))
    escaped_tag = tag.replace("'", "''")
    cursor = connection.cursor()
    try:
        cursor.execute(f"ALTER SESSION SET QUERY_TAG = '{escaped_tag}'")
        cursor.execute(safe_query, parameters or None)
        frame = cursor.fetch_pandas_all()
        if not isinstance(frame, pd.DataFrame):
            raise RuntimeError("Snowflake connector did not return a pandas DataFrame")
        frame.columns = [str(column).lower() for column in frame.columns]
        return frame
    finally:
        cursor.close()
