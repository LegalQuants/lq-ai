# Certificates directory

The nginx overlay mounts this directory (or `LQ_AI_TLS_CERT_DIR`, if set)
read-only at `/etc/nginx/certs/`. Place exactly two PEM files here:

| File | Contents |
| --- | --- |
| `fullchain.pem` | Server (leaf) certificate first, then any intermediate CA certificates, concatenated. Do **not** include the root. |
| `privkey.pem` | The unencrypted private key for the leaf certificate. |

Never commit real certificates or keys — this directory is intentionally
empty in source control (`.gitkeep` only), and the repo-wide `*.pem` rule in
`.gitignore` keeps `fullchain.pem` / `privkey.pem` out of git.

## Rotation

nginx reads certificates once at startup. After replacing the files, apply
them with a zero-downtime reload:

```bash
docker compose -f docker-compose.yml -f deploy/reverse-proxy/nginx/docker-compose.proxy.yml \
  exec nginx nginx -s reload
```

Set a calendar/monitoring reminder keyed to your CA's cert lifetime — nginx
serves an expired certificate without complaint. A quick expiry check:

```bash
openssl x509 -in fullchain.pem -noout -enddate
```

## Generating a quick self-signed pair (smoke-testing only)

```bash
openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
  -keyout privkey.pem -out fullchain.pem \
  -subj "/CN=lq.example.internal" \
  -addext "subjectAltName=DNS:lq.example.internal"
```

Browsers and `curl` will warn (use `curl -k`) — fine for verifying the
recipe, not for real use. For production, see the internal-CA section in
[`../README.md`](../README.md).
