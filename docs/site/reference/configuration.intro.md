Two things the tables below can't tell you on their own.

**Tier numbers are security levels — lower is stronger.** Tier 1 (local, air-gap-capable) is
the strongest posture; Tier 5 (consumer or free endpoints) is the weakest. Setting a
`minimum_inference_tier` of N on a request, a project, or a skill means "Tier N or stronger":
the gateway allows a routed tier of N or any lower number and refuses anything weaker with
HTTP 403 (`tier_below_minimum`); when more than one declaration applies at once, the strictest
(lowest number) wins. A tier is also only as good as what the operator says it is — the
`tier` on a provider entry, or an `inference_tiers` override for a provider or a single model,
is a claim about the hosting and contract behind that account, and nothing here checks it. The
same provider can be Tier 4 under a standard commercial account and Tier 3 under a
zero-data-retention agreement; which one actually applies is on the operator to verify.

**A setting existing here doesn't mean a running container receives it.** The backend table
lists everything `api/app/config.py` can read, but `docker-compose.yml` only forwards an
explicit list of variables into each service — not the whole root `.env`.
`LQ_AI_CHAT_HISTORY_TOKEN_BUDGET` and `LQ_AI_CHAT_HISTORY_MAX_MESSAGES`, for example, are both
in `.env.example` and in the table below, yet the default Compose file doesn't pass either to
`api` as of the checked commit — set them in `.env` alone and nothing changes. To actually use
a setting that isn't forwarded, add it to the service's `environment:` block and recreate the
service.
