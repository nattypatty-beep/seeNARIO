#!/bin/bash
cd "$(dirname "$0")" || exit 1
source ./keys.sh || { echo "Create keys.sh first (see instructions)"; exit 1; }

gcc main.c -o visionnav -lcurl || { echo "Compile failed"; exit 1; }

trap 'kill 0' EXIT
python3 uploader.py &
./visionnav
