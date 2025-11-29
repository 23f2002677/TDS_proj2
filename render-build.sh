#!/usr/bin/env bash
set -eux

# Install Python deps
pip install -r requirements.txt

# Create browser cache directory
mkdir -p /opt/render/.cache/ms-playwright

# Install Chromium into that directory
PLAYWRIGHT_BROWSERS_PATH=/opt/render/.cache/ms-playwright python -m playwright install chromium --with-deps
