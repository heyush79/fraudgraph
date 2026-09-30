#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 22.04/24.04 VM as a public FraudGraph console. Idempotent:
# run it again after a `git pull` to rebuild and restart.
#
#   curl -fsSL https://raw.githubusercontent.com/heyush79/fraudgraph/main/deploy/bootstrap.sh | bash
#
# or, from a clone:  bash deploy/bootstrap.sh
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/heyush79/fraudgraph.git}"
DIR="${DIR:-$HOME/fraudgraph}"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

say "1/5 Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi
DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"      # group membership applies from the next login

say "2/5 Firewall: open 80 and 443"
# Oracle Cloud's Ubuntu images ship iptables rules that drop everything except SSH, on top of
# the cloud security list. Both have to allow the ports; this handles the VM's half.
if sudo iptables -S INPUT 2>/dev/null | grep -q -- "-j REJECT"; then
  for port in 80 443; do
    sudo iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null \
      || sudo iptables -I INPUT 5 -m state --state NEW -p tcp --dport "$port" -j ACCEPT
  done
  sudo iptables -C INPUT -p udp --dport 443 -j ACCEPT 2>/dev/null \
    || sudo iptables -I INPUT 5 -p udp --dport 443 -j ACCEPT
  command -v netfilter-persistent >/dev/null && sudo netfilter-persistent save || true
fi

say "3/5 Code"
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only; else git clone "$REPO_URL" "$DIR"; fi
cd "$DIR"

say "4/5 Settings"
if [ ! -f deploy/public.env ]; then
  cp deploy/public.env.example deploy/public.env
  ip="$(curl -fsS https://api.ipify.org || true)"
  [ -n "$ip" ] && sed -i "s/^FRAUDGRAPH_DOMAIN=.*/FRAUDGRAPH_DOMAIN=${ip//./-}.sslip.io/" deploy/public.env
  if [ -t 0 ]; then
    read -r -s -p "Groq API key (Enter to skip; the console works without the analyst): " key; echo
    [ -n "$key" ] && sed -i "s/^GROQ_API_KEY=.*/GROQ_API_KEY=${key}/" deploy/public.env
  fi
  chmod 600 deploy/public.env
fi
grep -q '^FRAUDGRAPH_DOMAIN=.\+' deploy/public.env || { echo "set FRAUDGRAPH_DOMAIN in deploy/public.env and re-run"; exit 1; }

say "5/5 Build and start (the first build takes 10-15 minutes)"
$DOCKER compose -f docker-compose.yml -f deploy/docker-compose.public.yml --env-file deploy/public.env \
  --profile demo up -d --build

domain="$(grep '^FRAUDGRAPH_DOMAIN=' deploy/public.env | cut -d= -f2)"
say "Done. https://${domain}"
echo "The certificate is issued on the first request; give it a minute."
echo "The scorer serves the model shipped in ml-scorer/registry/ from the start."
echo "To retrain on this VM's own traffic after an hour or two:  make train TRAIN_HOURS=2"
