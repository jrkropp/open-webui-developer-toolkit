"""Open WebUI manifest describing the Responses manifold."""

MANIFEST = """
title: OpenAI Responses API Manifold
id: openai_responses
author: Justin Kropp
author_url: https://github.com/jrkropp
git_url: https://github.com/jrkropp/open-webui-developer-toolkit/blob/main/functions/pipes/openai_responses_manifold/openai_responses_manifold.py
description: Brings OpenAI Response API support to Open WebUI, enabling features not possible via Completions API.
required_open_webui_version: 0.6.28
requirements: aiohttp, fastapi, pydantic>=2
version: 0.9.7
license: MIT

DISCLAIMER - PLEASE READ:
This is an experimental restructure build that modularizes the pipe under src/ and re-bundles it into a single file.
Use the version in the alpha-preview or main branches instead.
"""
