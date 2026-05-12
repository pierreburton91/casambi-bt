#!/bin/bash
mkdir -p /casambi-bt
# Make env vars persist for future shells
echo "set -a; source /casambi-bt/.env; set +a" >> ~/.bashrc
# Load them now for the current process
set -a
source /casambi-bt/.env
set +a
# Install dependencies
pipenv install --dev -e .