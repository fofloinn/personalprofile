# Optional Home Assistant HTTPS (no subscription)

This is an **explicit exception** to HA's private-only baseline, not part of normal
website setup. It reuses the existing nginx public 80/443 listeners and ACME volumes.
The website's GET-only/public-admin restrictions and loopback-only SSH admin binding
are unchanged. No HA, Eufy, Ajax, DNS, router, Google project or device settings are
automated. No subscription, new domain, billing account or paid API is required.

## Privacy gate — read before preparing

HTTPS encrypts transport; it **does not guarantee no PII exposure**. This exposes HA's
login/OAuth endpoint and, after authentication, HA data and services (including the
WebSocket API). Strong unique credentials, MFA, patched HA/custom integrations, and
correct access controls are essential. Audit the login page, auth providers and stock
static assets locally for identifying content before enabling. Never use a trusted
network/auth bypass to make the checks pass. Do not change existing MFA/auth providers.

The public route is an allowlist: `/`, stock `/static/` and frontend assets, selected
`/auth/` flows, `/api/`, `/api/websocket`, `/api/google_assistant`. All other paths return
404, including `/local/`, `/media/`, camera/image/tts/media proxy URLs, webhooks and
custom integration assets. This deliberately limits remote UI features; use the private
path for administration/full UI. Do not relax the allowlist to make cameras work.
An installed custom integration could change the meaning of an allowed route: audit
that separately. The gate cannot automatically prove absence of private data.

HA request/error logging is disabled at nginx (error logs can contain OAuth URLs).
Forwarded client IP is overwritten, not appended to untrusted incoming headers.
No query strings, auth headers, cookies or bodies are printed by the setup checks;
response bodies are discarded. HA itself still keeps its own private authentication/
integration logs. Keep those, local settings and backups private; do not share raw
diagnostics or `docker compose config`. The prepared source/bind IPs are printed **only
to the operator's private terminal** for UI entry. There are no identifying fixtures.
The existing public website may intentionally contain personal content; this feature
does not change or claim to anonymize that website.

## Before running on the NUC

1. Transfer the reviewed website changes to the existing Linux checkout. Do **not**
   run on a workstation. Keep the existing private `.env`, certificates and data
   volumes; do not copy any private files back to a developer machine.
   Docker Engine 28+ and Compose **2.33.1+** are required (`gw_priority` support).
2. Use **`bash scripts/production-compose.sh`** instead of
   `docker compose -f compose.production.yaml` for every production command.
   `setup-production.sh` already does this. This preserves the optional dedicated
   interface across upgrades/recreation. Do not use another Compose project name or
   drop the generated override; that can remove the source interface and break HA.
3. In your private HA UI confirm the reserved LAN IPv4 matches the existing
   `bind_address` you configured. The script asks for it; it never reads HA `.local`,
   `.storage`, `.env`, accounts, entities, rooms or camera state.
4. Select an unused RFC1918 `/24`–`/29` Docker subnet after checking **all** LAN,
   Docker and VPN ranges, including disconnected VPNs. There is deliberately no
   default. The first usable address is the gateway, the second is nginx's stable
   source. Automated checks reject visible route and Docker-network overlaps.
5. Review the host firewall to permit that **single proxy IP** to the NUC's reserved
   LAN address on 8123. Keep other container/guest/IoT clients blocked; do not expose
   Eufy's loopback controls, media ports or private network. The script does not
   change firewall rules. Only nginx joins the new network, never WordPress/DB/Eufy.
6. Retain a working private HA connection and separate SSH recovery session.
   `.local` must be owned by the deployment user with mode 700. Run as that user,
   not with sudo; if Docker previously auto-created the empty directory as root,
   have the operator correct its ownership/permissions locally first.
   The generated `ha-nginx` subdirectory uses 755 and its non-secret snippets 644
   so capability-restricted nginx can read them. The **unmounted `.local` parent
   remains 700**; settings/Compose override remain 600. Never put credentials,
   service-account JSON or other private data in the nginx snippets directory.

## Two invocations of one script, with a mandatory UI stop

From the **website checkout on the NUC**:

```sh
python3 scripts/setup-ha-https.py prepare
```

Answer the LAN address/subnet prompts privately and confirm the network review.
Preparation recreates **only nginx** to attach the dedicated interface; the website
can have a brief proxy restart. It does not stop WordPress or request a certificate.
It installs only a container-loopback HTTP probe; no HA TLS vhost exists yet.
The existing port-80 ACME webroot serves `ha.fnl.life`; other HA HTTP paths return 404.

Follow the exact printed values in **HA 2026.9.4: Settings → System → Network →
HTTP server**:

- Trust X-Forwarded-For: **on**.
- Trusted proxies: **only the printed single nginx IPv4** (no CIDR/network ranges).
- Preserve the existing reserved LAN bind address and port **8123**.
- IP banning: **on**; failed login threshold: **5**.
- TLS stays off inside HA; nginx terminates TLS.
- Preserve MFA/authentication providers; no trusted-network login bypass.

Saving restarts HA. Reconnect over the existing private connection and **confirm
within five minutes**, otherwise HA rolls back. Migrated HTTP YAML is ignored;
never change `.storage` or attempt a YAML workaround.

After confirming recovery, MFA and the privacy review:

```sh
python3 scripts/setup-ha-https.py enable
```

This refuses to proceed unless the actual nginx-to-LAN forwarded `/api/` probe returns
**401**, not 400/200/redirect. `proxy_bind` pins the source even with multiple nginx
interfaces; `gw_priority: 100` makes the dedicated interface the default route to the
host's LAN address (rather than the website bridge, which can fail reverse-path checks).
This checks the actual Docker-to-host route, not `host-gateway` or an
assumed NAT path. If the check fails, fix the exact UI trust, binding or firewall via
the private path; do not widen the trusted range.

The second explicit gate confirms:

- `ha.fnl.life` CNAME points to the existing website and its public address. Check
  public resolution/propagation and IPv6 too; a stray AAAA must not route elsewhere.
- Existing 80/443 router forwards work; **no new forwards**, particularly not 8123.
- Consent to Let's Encrypt terms and public certificate-transparency disclosure
  of the hostname. The existing certbot account must already be registered.

Only then does certbot request a **separate** `ha.fnl.life` certificate through the
running webroot. It never expands/replaces the website certificate or stops nginx.
Existing certbot renewal runs every 12 hours; nginx watches **all** certificate
lineages every 60 seconds and reloads on a changed chain/key.

After another backend check, the script installs the allowlisted TLS vhost, validates
nginx, reloads it, and checks HTTPS certificate validation, unauthenticated API 401
and denied sharing paths. Failure withdraws the HA vhost and restarts **only nginx**
to close old authenticated WebSockets (a reload alone keeps these alive).
This briefly interrupts website connections, not WordPress/database processes.
If rollback cannot restore nginx, it stops **the proxy** to fail closed (website outage).
Do not declare deployment successful after a failed check.

## External acceptance and rollback

If preparation fails, do not enable public access or delete the prepared settings.
Run `python3 scripts/setup-ha-https.py diagnose` from the same website checkout.
This read-only command reports configuration/status exit codes and fixed error
categories from recent proxy logs, without printing raw output or private values.
It does not restart services, create configuration, or request certificates.
An unrecognized category is not proof of success; inspect raw errors only locally.
Command failures now identify the failed stage without echoing command arguments.
Once the underlying issue is resolved, `prepare` resumes using the saved settings.

From a separate external network, without credentials/tokens (never use `-k`):

```sh
curl --silent --output /dev/null --write-out '%{http_code}\n' https://ha.fnl.life/api/
curl --silent --output /dev/null --write-out '%{http_code}\n' https://ha.fnl.life/local/privacy-probe
curl --silent --output /dev/null --write-out '%{http_code}\n' https://ha.fnl.life/api/webhook/privacy-probe
```

Expect **401, 404, 404** with a publicly valid certificate. Verify website public
admin/POST blocks and the SSH-only admin path still work. Keep only sanitized
pass/fail evidence, never page content or identifiers. Check 8123/vendor ports remain
unreachable from the Internet/guest network. No Google steps until these pass.

On the NUC, further operations use the same script:

```sh
python3 scripts/setup-ha-https.py settings  # private UI values; do not share output
python3 scripts/setup-ha-https.py check     # no body/token output
python3 scripts/setup-ha-https.py disable   # withdraw HA; brief proxy restart closes active connections
bash scripts/production-compose.sh up -d --wait  # ordinary lifecycle, preserves HA option
```

`prepare` can resume an interrupted preparation with the same settings. `enable`
refuses an already enabled installation; use `check`. Generated configuration is
owner-private in ignored `.local`; retain it for normal redeploys. Disabling retains
the prepared address and certificate so future activation repeats the operator gates.
`check` withdraws an enabled route if acceptance fails. Do not run website lifecycle
commands concurrently with this setup; the HTTPS script serializes its own invocations.
No automatic reset of HA's UI settings, certificate deletion or network cleanup occurs.

Google setup is later: no project, service account, billing or account linking here.
Use the no-cost manual integration, `expose_by_default: false`, initially no entities;
only a deliberately chosen generic harmless helper may be shared in a later phase.
Google will receive the public OAuth hostname and any deliberately shared entity
names/state. Store future service-account JSON only in ignored owner-private HA
configuration, never source control. No alarms, cameras, locks or actual devices
should be exposed merely to test discovery.

## Offline developer verification

```sh
python3 scripts/test-ha-https.py
python3 scripts/test-setup-production.py  # mocked bash lifecycle checks, Linux
python3 scripts/check-ha-https-offline.py
```

The integration check requires already cached `nginx:stable-alpine` and
`python:3.14-slim` images; it never pulls/installs dependencies. It uses disposable
internal Docker networks, synthetic backend responses and self-signed test
certificates, with **no host ports** or external network. It checks separate SNI
certificates, forwarding/source identity on multi-interface nginx, WebSocket upgrade,
route/privacy restrictions, unchanged website behavior, disabled state and actual
HA-only certificate-watch reload. It does not reproduce the NUC's LAN/firewall;
the mandatory deployment probe remains the proof of that host's routing/trust.
