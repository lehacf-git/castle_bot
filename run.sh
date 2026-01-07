#!/bin/sh

castle run --minutes 10 --mode training \
  --limit-markets 100 \
  --min-volume 0 \
  --min-open-interest 50
