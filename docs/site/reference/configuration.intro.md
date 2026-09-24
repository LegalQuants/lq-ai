Two things the tables below cannot tell you on their own.

**Tier numbers are security levels, and lower is stronger.** Tier 1 (local, air-gap-capable)
is the strongest posture and Tier 5 (consumer or free endpoints) the weakest. A
`minimum_inference_tier` of N — declared on a request, a project, or a skill — means "Tier N
or stronger": the gateway allows a routed tier of N or any lower number and refuses anything
higher with HTTP 403 (`tier_below_minimum`); where several declarations apply, the lowest
number wins. A tier is also only what the operator says it is: the `tier` on a provider
entry, or an `inference_tiers` override for a provider or a single model, is a statement
about the hosting and contract behind that account which nothing here verifies. The same
provider is Tier 4 under a standard commercial account and Tier 3 under a zero-data-retention
agreement; checking which one applies is the operator's job.

**A setting existing is not the same as the container receiving it.** The backend table lists
what `api/app/config.py` can read, but `docker-compose.yml` forwards an explicit list of
variables into each service, not the whole root `.env`. `LQ_AI_CHAT_HISTORY_TOKEN_BUDGET` and
`LQ_AI_CHAT_HISTORY_MAX_MESSAGES`, for example, appear in `.env.example` and in the table, yet
the default Compose file does not pass them to `api` as of the checked commit — set in `.env`
alone, they change nothing. To use a setting that is not forwarded, add it to the service's
`environment:` block and recreate the service.
