# Tailnet-Hosted Ollama for the Gateway

[Tailscale](https://tailscale.com/) is a networking platform that connects devices securely into a private network called a **tailnet**. Devices on the same tailnet can communicate without exposing their services directly to the public internet.

[Ollama](https://ollama.com/) is a tool for running large language models locally. It provides an HTTP API that applications such as the LQ.AI inference gateway can use for model inference.

This recipe covers the setup when Ollama runs on a separate GPU host on your tailnet and the LQ.AI gateway runs on another machine.

---

## When to Use This

Use this recipe when:

- Ollama runs on a separate GPU machine from the LQ.AI gateway.
- Both machines are connected to the same Tailscale tailnet.
- You want the gateway to reach Ollama over HTTPS without exposing Ollama to the public internet.

### Architecture

```text
Gateway
    |
    | HTTPS
    v
https://<host>.<tailnet>.ts.net
    |
    | Tailscale Serve
    v
127.0.0.1:11434
    |
    v
Ollama on the GPU host
```

Tailscale Serve terminates HTTPS on the GPU host and forwards requests to Ollama on the host's loopback interface.

---

## Prerequisites

You need:

- A machine running the LQ.AI gateway.
- A separate GPU host with Ollama installed and running.
- Tailscale installed and authenticated on the GPU host.
- Both machines connected to the same tailnet.
- **MagicDNS** enabled for the tailnet.
- **HTTPS Certificates** enabled for the tailnet.

> **Note:** MagicDNS provides DNS names for devices on the tailnet. HTTPS Certificates allow Tailscale to provide a publicly trusted certificate for the device's `*.ts.net` hostname.
> See the Tailscale documentation for [MagicDNS](https://tailscale.com/kb/1081/magicdns) and [HTTPS Certificates](https://tailscale.com/kb/1153/enabling-https).

---

## Quick Start

### 1. Verify Ollama on the GPU Host

Make sure Ollama is installed and running on the GPU host. Verify that its local API responds:

```bash
curl http://127.0.0.1:11434/api/tags
```

The response should contain the models available to Ollama.

### 2. Expose Ollama with Tailscale Serve

On the GPU host, run:

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:11434
```

Check the active configuration:

```bash
tailscale serve status
```

The Ollama endpoint is now available over the tailnet at:

```text
https://<host>.<tailnet>.ts.net
```

*Example:* `https://gpu-box.example.ts.net` (the exact hostname depends on your Tailscale machine name and tailnet DNS name).

### 3. Configure the Gateway

On the machine running the LQ.AI gateway, set:

```env
OLLAMA_BASE_URL=https://<host>.<tailnet>.ts.net
```

*Example:* `OLLAMA_BASE_URL=https://gpu-box.example.ts.net`

Set this in the environment used by the gateway, then recreate or restart the gateway so that it loads the new value.

### 4. Verify the Connection

From the gateway host, verify that the Tailscale HTTPS endpoint is reachable:

```bash
curl -f https://<host>.<tailnet>.ts.net/api/tags
```

A successful response confirms that the gateway host can reach the Ollama API through the Tailscale HTTPS endpoint.

---

## Technical Details

### Why HTTPS is Required

The gateway's LLM provider egress policy allows HTTPS destinations without the local-host restriction. Plaintext HTTP is restricted strictly to explicitly local inference targets.

For a remote Ollama host on a tailnet, use:

```env
OLLAMA_BASE_URL=https://<host>.<tailnet>.ts.net
```

The Tailscale hostname uses a publicly trusted HTTPS certificate, so the gateway container does not need a custom CA bundle for this connection.

### Why Plain HTTP to a Tailscale IP is Refused

Tailscale addresses use the `100.64.0.0/10` CGNAT range. The gateway's LLM egress policy deliberately does not treat that range as a permitted local target for plaintext HTTP.

Therefore, this configuration is refused:

```env
OLLAMA_BASE_URL=http://100.x.y.z:11434
```

The gateway reports an error of this form:

```text
plaintext http base_url is only permitted for local providers
(host.docker.internal, localhost, ollama, vllm, or a loopback/private IP);
host '100.x.y.z' must use https
```

This refusal is intentional. The egress guard prevents LLM prompts from being sent over plaintext HTTP to a remote host. HTTPS is required for remote destinations, so the supported tailnet configuration uses the Tailscale `*.ts.net` hostname instead.

For egress policy details, see
[ADR 0014 — Gateway egress boundary](../../docs/adr/0014-gateway-egress-boundary-for-tool-providers.md).

---

## Alternatives to Tailscale Serve

Tailscale Serve is the simplest option when Ollama runs directly on the GPU host. Other HTTPS-capable service patterns can also be used:

- **[Tailscale Services](https://tailscale.com/kb/1573/tailscale-services):** Provides service-level identities and routing within a tailnet.
- **Caddy or Reverse Proxy:** A reverse proxy can terminate HTTPS and forward requests to Ollama. See [`deploy/caddy-tailscale/README.md`](../caddy-tailscale/README.md) for the general pattern.

Regardless of the mechanism used, a remote Ollama endpoint should always be configured with an HTTPS `OLLAMA_BASE_URL`.

---

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