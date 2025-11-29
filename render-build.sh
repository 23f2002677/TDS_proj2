#!/usr/bin/env bash
set -eux

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers (Chromium) inside the Render environment
python -m playwright install chromium --with-deps

# Ensure Playwright cache directory is accessible
chmod -R 777 /opt/render/.cache/ms-playwright || true
