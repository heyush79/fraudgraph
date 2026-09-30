#!/bin/sh
# Run by the nginx image's entrypoint before nginx starts. PUBLIC_MODE=true switches on
# the read-only rule (public-mode.conf); anything else leaves it out.
set -eu
if [ "${PUBLIC_MODE:-false}" = "true" ]; then
    cp /etc/nginx/fraudgraph-public-mode.on /etc/nginx/fraudgraph-public-mode.conf
    echo "public mode: only reads and questions to the analyst are allowed"
else
    : > /etc/nginx/fraudgraph-public-mode.conf
fi
