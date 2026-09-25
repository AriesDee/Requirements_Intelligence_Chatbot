"""Shared Vertex AI client factory — uses GOOGLE_APPLICATION_CREDENTIALS for auth."""
import os

import google.genai as genai

_PROJECT  = os.getenv("GOOGLE_CLOUD_PROJECT",  "gcp-abs-sbt01-psbx-sbx-prj-01")
_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")


def make_client() -> genai.Client:
    return genai.Client(vertexai=True, project=_PROJECT, location=_LOCATION)
