# Use Ollama on another computer over Tailscale

You can point LQ.AI at an Ollama server on your private Tailscale network. Make sure that computer has the model you choose.

## Apply the address change

After changing `OLLAMA_BASE_URL` in the Compose environment, recreate the gateway container. Restarting it alone keeps the old value. Also check that the working `gateway.yaml` reads that variable.

### Details

```env
OLLAMA_BASE_URL=https://<host>.<tailnet>.ts.net
```

*Example:* `OLLAMA_BASE_URL=https://gpu-box.example.ts.net`

Set this in the environment used by the gateway, then recreate it:

```bash
docker compose up -d --force-recreate gateway
```

A plain `docker compose restart gateway` keeps the environment the container was created with — it does not pick up the new value. `gateway.yaml` reads the variable as `base_url: ${OLLAMA_BASE_URL:-http://ollama:11434}` ([`gateway.yaml.example`](../../gateway.yaml.example)).

## AI and tool connections have different rules

AI connections allow some private-network addresses. External tool connections use stricter rules: HTTPS, an approved hostname and public network addresses. An address that works for Ollama won't necessarily be accepted for a tool.

### Details

The LLM-provider rule lives in [`base_url_policy.py`](../../gateway/app/providers/base_url_policy.py) — it's what this recipe's `OLLAMA_BASE_URL` has to satisfy. Tool providers — the research sources and MCP servers declared under `tool_providers:` — go through a separate, stricter guard, [`tool/egress.py`](../../gateway/app/providers/tool/egress.py): HTTPS is required with no local exception at all, the host must be on that provider's own allowlist, and every address the host resolves to must be public. A tailnet-hosted MCP server is refused under that guard even over HTTPS, because its `*.ts.net` name resolves to a `100.64.0.0/10` address — this recipe is for Ollama and other LLM providers only.

## Prepare both computers

Run Ollama on the model computer and confirm its `/api/tags` response lists the installed models. Both computers need access to the same private network; the documented recipe uses Tailscale DNS names and HTTPS certificates. On the Ollama computer, Tailscale Serve forwards HTTPS to its local port 11434.

### Details

You need:

- A machine running the LQ.AI gateway.
- A separate GPU host with Ollama installed and running.
- Tailscale installed and authenticated on the GPU host.
- Both machines connected to the same tailnet.
- **MagicDNS** enabled for the tailnet.
- **HTTPS Certificates** enabled for the tailnet.

> **Note:** MagicDNS provides DNS names for devices on the tailnet. HTTPS Certificates allow Tailscale to provide a publicly trusted certificate for the device's `*.ts.net` hostname.
> See the Tailscale documentation for [MagicDNS](https://tailscale.com/kb/1081/magicdns) and [HTTPS Certificates](https://tailscale.com/kb/1153/enabling-https).

## Configure and verify the gateway

Set `OLLAMA_BASE_URL` to the model computer's https:// address and confirm the gateway service receives that environment value. Recreate the gateway after changing its environment. Check the working `gateway.yaml` aliases and installed model names, then test connectivity from the gateway's actual environment. A successful model-list request establishes connectivity, not that chat and document search work.

### Details

The gateway's LLM provider egress policy allows HTTPS destinations without the local-host restriction; plaintext HTTP is restricted to explicitly local inference targets (see "If plaintext HTTP is refused" below). The Tailscale hostname carries a publicly trusted HTTPS certificate, so the gateway container needs no custom CA bundle for this connection.

`gateway.yaml`'s model aliases map to specific Ollama tags — for example the `local` alias defaults to `ollama-local` / `qwen3.5:9b` ([`gateway.yaml.example`](../../gateway.yaml.example)). If that tag isn't pulled on the model computer, the alias fails even though the endpoint itself is reachable.

## If plaintext HTTP is refused

The guard does not treat Tailscale's 100.x addresses as an allowed local HTTP target. Use the HTTPS hostname described by the recipe. Do not bypass the transport check just because the private network itself encrypts traffic — the guard stops LLM prompts from leaving the gateway in plaintext; it isn't a claim about the tailnet's own security.

### Details

Tailscale addresses use the `100.64.0.0/10` CGNAT range, which the gateway's LLM egress policy deliberately does not treat as a permitted local target for plaintext HTTP. So this configuration is refused:

```env
OLLAMA_BASE_URL=http://100.x.y.z:11434
```

The gateway reports an error of this form:

```text
plaintext http base_url is only permitted for local providers
(host.docker.internal, localhost, ollama, vllm, or a loopback/private IP);
host '100.x.y.z' must use https
```

This refusal is intentional. HTTPS is required for remote destinations, so the supported tailnet configuration uses the Tailscale `*.ts.net` hostname instead.

## Test from the gateway's network

A successful curl on the Ollama computer does not establish that the gateway can reach it. Use the HTTPS hostname in `OLLAMA_BASE_URL` and verify DNS, certificates and access from the gateway environment. A bare Tailscale IP over HTTP is rejected by the provider-address policy, even though the machines are on a private network.

### Details

From the gateway host, check that the Tailscale HTTPS endpoint is reachable:

```bash
curl -f https://<host>.<tailnet>.ts.net/api/tags
```

A successful response here confirms the gateway *host* can reach Ollama — but the gateway itself runs in a container, and it's the container that has to resolve the `*.ts.net` name. The gateway image ships no `curl`, so test from inside it with Python instead:

```bash
docker compose exec gateway python -c "import urllib.request; print(urllib.request.urlopen('https://<host>.<tailnet>.ts.net/api/tags').status)"
```

A `200` here means the gateway's own network can reach Ollama; a resolution error means the container isn't seeing MagicDNS even though the host is.

## Check and publish the model endpoint

Run these on the Ollama computer:

```bash
curl -f http://127.0.0.1:11434/api/tags
sudo tailscale serve --bg --https=443 http://127.0.0.1:11434
tailscale serve status
```

Then, on the gateway machine, set `OLLAMA_BASE_URL` to that HTTPS hostname and recreate — not restart — the gateway (see "Apply the address change" above), and confirm the connection from the gateway's own network (see "Test from the gateway's network" above).

## Alternatives to Tailscale Serve

Tailscale Serve is the simplest option when Ollama runs directly on the GPU host. Other HTTPS-capable service patterns can also be used:

- **[Tailscale Services](https://tailscale.com/kb/1573/tailscale-services):** Provides service-level identities and routing within a tailnet.
- **Caddy or Reverse Proxy:** A reverse proxy can terminate HTTPS and forward requests to Ollama. See [`deploy/caddy-tailscale/README.md`](../caddy-tailscale/README.md) for the general pattern.

Regardless of the mechanism used, a remote Ollama endpoint should always be configured with an HTTPS `OLLAMA_BASE_URL`.

## References

- **Tailscale Documentation:**
  - [What is a tailnet?](https://tailscale.com/kb/1136/tailnet)
  - [Tailscale Serve](https://tailscale.com/kb/1242/tailscale-serve)
  - [MagicDNS](https://tailscale.com/kb/1081/magicdns)
  - [Enabling HTTPS](https://tailscale.com/kb/1153/enabling-https)
- **Ollama Documentation:** [ollama.com](https://ollama.com/)
- **Internal References:**
  - [Caddy + Tailscale deployment recipe](../caddy-tailscale/README.md)
  - [ADR 0014 — Gateway egress boundary](../../docs/adr/0014-gateway-egress-boundary-for-tool-providers.md)
