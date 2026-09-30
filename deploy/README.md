# Running FraudGraph in public

There are three ways to put FraudGraph in front of someone else. They differ in what is live
and in what they cost.

| | What they see | Cost | Stays up |
|---|---|---|---|
| **Replay** (GitHub Pages) | a recorded session of the real pipeline, replayed at its original timing, with recorded analyst answers | free | always |
| **Share** (`make share`) | your laptop's live stack, through a temporary HTTPS URL | free | while the command runs |
| **Live VM** (this folder) | the full live stack on a free cloud VM, with its own HTTPS address | free (Oracle Cloud Always Free) | always |

The replay is the link for a CV or a README: it cannot go down, cannot be abused and costs
nothing. Share is for an interview: the interviewer opens a real URL and watches real
transactions arrive, and you close it afterwards. The VM is for when you want the live system up
permanently.

## Share: a public URL for the stack on your laptop

```bash
brew install cloudflared      # once
make demo                     # the full stack, if it is not already up
make share                    # prints https://<random-words>.trycloudflare.com
```

`make share` rebuilds the dashboard read-only, turns on the analyst's rate limits (`public.env`
values), and opens a Cloudflare quick tunnel to it: no account, no DNS, a new random address each
time. Ctrl-C closes the tunnel; `make demo` puts the local settings back.

## Live VM: Oracle Cloud Always Free

Oracle's Always Free tier includes an Arm VM with 4 cores and 24 GB of memory, which runs the
whole stack with room to spare. Every image used here is multi-architecture, so nothing changes
for Arm.

**1. Create the VM** (the one step only you can do)

1. Sign up at [cloud.oracle.com](https://cloud.oracle.com). A card is needed to verify identity;
   Always Free resources are not charged. Setting a budget alert of 1 (any currency) under
   *Billing → Budgets* makes sure of it.
2. *Compute → Instances → Create instance*:
   - Image: **Canonical Ubuntu 24.04**
   - Shape: *Ampere* → **VM.Standard.A1.Flex**, **4 OCPUs, 24 GB** (the Always Free allowance)
   - Networking: keep "assign a public IPv4 address"
   - SSH keys: upload your public key (`~/.ssh/id_ed25519.pub`)

   "Out of capacity" is common for A1 in busy regions. Try another availability domain, or try
   again later; capacity frees up through the day.
3. Open the ports in the cloud firewall: the instance's subnet → *Security List* → *Add Ingress
   Rules*: source `0.0.0.0/0`, TCP, destination ports **80** and **443**, and UDP **443**.

**2. Install**

```bash
ssh ubuntu@<public-ip>
curl -fsSL https://raw.githubusercontent.com/heyush79/fraudgraph/main/deploy/bootstrap.sh | bash
```

The script installs Docker, opens 80/443 in the VM's own firewall (Oracle's Ubuntu images block
them on top of the security list), clones the repository, writes `deploy/public.env` (it asks for
the Groq key, and names the VM `<ip-with-dashes>.sslip.io`, a free hostname that resolves to your
IP), then builds and starts everything. The first build takes 10 to 15 minutes.

**3. Open it**

`https://<ip-with-dashes>.sslip.io`. Caddy obtains the certificate on the first request.

**4. The model**

The repository ships a trained model (`ml-scorer/registry/v3`), so the scorer serves from the
first minute. To retrain it on the VM's own traffic after an hour or two:

```bash
cd ~/fraudgraph && make train TRAIN_HOURS=2
```

(With no model at all, the engine runs in DEGRADED mode, deciding with rules alone. That is the
designed fallback, and stopping the scorer is a good way to show it.)

## What the public can and cannot do

- **Only Caddy listens on the network.** Every other port is bound to 127.0.0.1 by the base
  compose file, so Postgres, Kafka, Redis, the engine's read API and the scorer's `/reload` are
  unreachable from outside.
- **Read-only.** The dashboard is built without the case status control, and its nginx refuses
  every request that is not a read or a question to the analyst. The UI flag is convenience; the
  nginx rule is the control.
- **Rate-limited analyst.** `public.env` sets per-visitor and global limits sized to Groq's free
  tier, and identical questions are answered from a cache. Over the limit, the console says so
  and tells the visitor when to try again.
- **No automatic reports.** The case service does not hand every case to the agent; at one case
  a second that would exhaust a free key in minutes.
- **The key stays on the VM**, in `deploy/public.env` (gitignored, mode 600).

## Running it

```bash
cd ~/fraudgraph
docker compose ps                                   # what is up
docker compose logs -f --tail=100 stream-engine     # one service's logs
bash deploy/bootstrap.sh                            # after a git pull: rebuild and restart
make recall RECALL_HOURS=1                          # what the live system is catching
```

Disk: `public.env` keeps two days of decisions in Kafka and runs the generator at 20 tps, about
4 GB of Kafka data at steady state. Cases accumulate in Postgres at roughly 100 MB a day;
to keep a week of them:

```bash
docker exec fraudgraph-postgres psql -U fraudgraph -d fraudgraph \
  -c "delete from cases where created_at < now() - interval '7 days'"
```
