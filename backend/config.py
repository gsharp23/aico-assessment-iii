"""Environment helpers shared by the API and the RAG pipeline."""

import os


def env(name: str, default: str = "") -> str:
    """Read an environment variable, treating an empty value as absent.

    Docker Compose substitutes an *unset* variable as an empty string rather than
    leaving it undefined. That means `os.environ.get("AWS_REGION", "us-east-1")`
    returns "" - not the default - and boto3 then fails with "You must specify a
    region". Using `or` instead of a dict default makes blank and missing behave
    the same way.
    """
    return os.environ.get(name) or default


def require(name: str) -> str:
    """Read a variable that has no safe default, and fail with a clear message."""
    value = env(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Copy .env.example to .env and fill it in, "
            "or check that the deploy workflow wrote it on the instance."
        )
    return value
