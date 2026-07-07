#!/bin/bash
# watch.sh
COMMAND="quarto render index.qmd"

fswatch -o index.qmd | while read -r; do
  echo "Change detected, running: $COMMAND"
  $COMMAND
done
