#!/bin/bash
# watch.sh
TARGET_DIR="index.qmd"
COMMAND="quarto render index.qmd"

fswatch -o "$TARGET_DIR" | while read -r; do
  echo "Change detected, running: $COMMAND"
  $COMMAND
done
