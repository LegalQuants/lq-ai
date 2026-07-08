#!/usr/bin/env bash
# Delete stale remote branches audited on 2026-07-08 (see docs/branch-audit-2026-07-08.md).
#
# Every branch listed below was verified to be fully contained in main:
# either its squashed patch-id already exists in main, or its tip exactly
# matches the head SHA of a merged PR whose content reached main.
#
# Safety:
#   - Dry-run by default; pass --execute to actually delete.
#   - Each branch is deleted only if its tip still matches the SHA recorded
#     at audit time. A branch that gained commits since the audit is skipped.
#
# Usage:
#   scripts/delete-stale-branches.sh            # preview
#   scripts/delete-stale-branches.sh --execute  # delete
set -euo pipefail

REMOTE="${REMOTE:-origin}"
EXECUTE=false
[[ "${1:-}" == "--execute" ]] && EXECUTE=true

git fetch "$REMOTE" --prune --quiet

deleted=0 skipped=0 gone=0
while IFS=$'\t' read -r branch audited_sha; do
  [[ -z "$branch" || "$branch" == \#* ]] && continue
  current_sha=$(git ls-remote --heads "$REMOTE" "refs/heads/$branch" | cut -f1)
  if [[ -z "$current_sha" ]]; then
    echo "GONE     $branch (already deleted)"; gone=$((gone+1)); continue
  fi
  if [[ "$current_sha" != "$audited_sha" ]]; then
    echo "SKIP     $branch (tip moved since audit: $current_sha)"; skipped=$((skipped+1)); continue
  fi
  if $EXECUTE; then
    git push "$REMOTE" --delete "$branch"
    echo "DELETED  $branch"
  else
    echo "WOULD-DELETE $branch"
  fi
  deleted=$((deleted+1))
done <<'BRANCHES'
chore/azure-cost-rates-de278	138217f3f691ebcdd79f019f390e3bc612123bb3
chore/bump-v0.4.1	895508eab1bb1d49d2c3b4f38134426571a480f8
chore/bump-v0.4.2	3f12470d9714d8e0d077fee1c0766444460479eb
chore/dockerignore-finder-duplicates	6aace22c1a6c3becb385ceb48dbff239de26afa2
chore/gateway-version-bump-v030	237ed8d679666a62c998baf383815b5bdff6a3b8
chore/pin-ruff-0-15-17	0e064635bfd5d880f75bbb5b327051570aca24c0
chore/v0.3.1-version-bump	e5108b145cfa89f5103e85b5776bbadc24244959
chore/v0.6.1	7e2fa89bc93f392dfffb1066770ac58345e3ad89
chore/v0.6.2-launcher-image-refresh	4121b7bb47ec25cfaf332f249d77f8a5ff5e9ba9
claude/practical-rubin-xsd077	3230681028e42fdd32a0b1742ccdb60ce3866f19
claude/test-coverage-dependabot-qns7bh	7bef293a429c0beac72f0acc728f5e4fa8d0f0e1
docs/add-roadmap-link	a832303155a2bbbacd67aa58957fef13e2c19ae0
docs/brief-tabular-ensemble-verification	46ee972e65804d1b1d077f51f3b4b58b12a8e970
docs/coding-agent-onboarding	c3ab78e2f3e297dbe9507cb01b92cb483da12642
docs/de-329-email-profile-edit	b2a26211c001bf2b10315ecef2e51256ad9404fe
docs/de-356-first-run-progress	6637b720edfd9e580c3db764e90b874556edbb19
docs/de-385-desktop-lockfile-version	e3f9167eef870247cd237238e5a71e7876f130df
docs/delete-204-fastapi-convention	2cce945d1b8722f9953900a081234f46cfed5745
docs/donna-run-reconciliation	0b6b262b3cc78c2ed889f6a027ad115840a1a4a0
docs/external-contribution-vetting	9a08b90f3c7c7c43d659f1c2c0646a8861e83cb2
docs/handoff-2026-06-01	a6d0207ee25af0efa5f8e6c2d28b05f0c75a458c
docs/handoff-2026-06-05	58a7babdcc97b1edaac335f6ffd4b1e34775f857
docs/handoff-2026-06-16	c54f67f16f034412fd0ecea2c18864baaa54e170
docs/handoff-2026-06-23	4b1327134286ee64619f8d03c218bfc6a5915de3
docs/handoff-2026-06-25	5905506d701dcaae1729c787cca3d798f1e9baf5
docs/handoff-pr5b-next	dbae9be5f2d502e95d20b5a22d217d9f435b4d93
docs/install-mac-flow-screenshots	dbce8dd68de49bc66b13e662d26c2bf47e0bae8e
docs/install-mac-screenshots	49df9ca372fde04cc50d60e62d8d9181004fd096
docs/launcher-protocol1-verified	5107bf41dc74dc95eb1ec8128281c9f03d35f5d0
docs/launcher-signing-verified	e35bcece8874e97bbdd6073123937b3884e4df6b
docs/m3-a3-retro-disclaimer-update	1b1598ccea74c0e3cbef33755c708aeda730ce5f
docs/m3-close-learn-pages-overhaul	d547534b7e12e8a3045497014e0a9006e8ffe5b7
docs/m3-close-learn-viz-audit	d1dd30bc2e8a5dde6ee5d2907eaab60a5d6937df
docs/m3-e1-deferred-enhancements	4e18f3f88f4e9ac83871fae0e7e1f2127a547885
docs/m3-e2a-capability-docs	c8921bc2fa820cf12ad89e00a6999f6aa44aa8d3
docs/m3-e2b-onboarding-audit	023be4a5f86582dfdf294c37cdd40194a2b147a2
docs/m3-e2c-playgrounds	8350f18bd351b3188e07f1f2c6fcc4f792118cfd
docs/m3-implementation-plan	fb697c6a0775b5593968bf2c1c7314119fa3fd2a
docs/m4-autonomous-layer-design	a33217c8325250582548d02baece5edfd9f5550c
docs/models-openapi-alias-fields	bb6ced2b19c1530589d9f920937850312e809b01
docs/observability-code-accuracy	956e25f2af512d0a48293209e78e1108de4264d9
docs/phase-c-corpus-decisions-confirmed	56ed48d42bbaf72895ce82ebe83792a951cc8e83
docs/release-honesty-reconcile-v0.5.0	51d43be2e88bdb2203660fc4da4a4d0974913f37
docs/skill-inputs-upstream-request	37778a553abb992665cb18c32fb5b3db0109ff46
docs/webui-db-bootstrap-hardening	678be16d1ccbf2d5cfe3671c8ab0f23a703aa77d
docs/wse-pr1c-handoff	fbd974eb3a48db66894e76b93674962eea2d0e4f
feat/autonomous-findings-readmodel	d4b22884f8ad00d6a9c0d150cf8cd8d46bea10a8
feat/autonomous-project-reassign-and-ownership	f6315051b44cf26d991d2a64ce9feb3b7ba538c1
feat/chat-multi-turn-memory	65dffb8ec6784ed6b8d72f2f84e2c56af5d616af
feat/courtlistener-tool-provider	712517bc4566fdb11eb65d3715e3310699edcece
feat/de-350-mcp-provenance	9ea1d7cc39447d3e44c352514ec77b850b0323b4
feat/de-373-openapi-drift-guard	ba5343da3e07083b3374bfc30022bdaff113a083
feat/donna-1-skill-inputs-de328	877a157fc92b4317851625e0177cc564f1a23339
feat/donna-2-message-file-ids	d3002e1af615fce80c099d8884aa95bed63a05d8
feat/donna-2b-file-content-injection	4c8714ef0decc3186eadc4fc22e7ce33f3242ff5
feat/donna-3-patch-users-me	933524061e619e25a1693827f01372947be4972d
feat/donna-4-deletion-status-users-me	58c02554dbfe84cf7dc696c97c5252fba491e5b9
feat/donna-5-navigable-tabular-citations	c6674a7d87faa3bbcc1947cd6aad50949774bbd3
feat/donna-6-tabular-ensemble-verification	148dd64cb14e93311c1b26a0dae317ed17e37c7f
feat/donna-7-runtime-provider-keys	29ec439280cc5b9b4872ae31f4c492064b3cb89b
feat/donna-8-autonomous-artifacts	1af178635f640ea24101382487db374beb07c4ba
feat/fiduciary-p1a1-caselaw-quote-verification	87c5f31e96ff77e9a40a6c48f98338e1900d938b
feat/fiduciary-p1a2-citation-ledger	3223c26fb8937647a2e3e3ea883b114f414afa2f
feat/fiduciary-p1a3-ledger-read-api	0325aeb0a68171e08ca2187733e95f73c4f1df4c
feat/fiduciary-p1b1-fiduciary-gate	34383e9a0effbc870b607c8333b18e434be1c87a
feat/fiduciary-p1b1b-caselaw-paraphrase-judge	7b0cb21408e18da19025b1c0fb765115a5f39eb4
feat/legal-research-mcp-plan	afa0938b04d64ee9678142178f5262f36ac186b0
feat/lqvern-m4-autonomous	316f8993dc25ae4856199b97cf5d2c9eb97e217b
feat/m3-close-anonymization-config-endpoint	6bbdcb9acdc5481dcfaf63abe53b1bd2d09e3189
feat/m3-close-de316-skill-author	498db80d663cd20be1b8efa1f616ffbaa32f961c
feat/m3-close-test-landscape-playground	7cc0edee694c2833f41ab5f9feaad3990fb37025
feat/m3-f1-trace-propagation	94a409874441dc8cbfff2dc48f663fe683b3d7cf
feat/m3-f2-domain-spans	7249ec1341d1c8e47a8449dbe16c811d2e5ea5fe
feat/m3-f3-deploy-observability	865c752dca9b1ab74b787f0fe37d24782156ad03
feat/macos-launcher	8b453238c7b1ef0676dae8b63c2005a7548ba20e
feat/mcp-client-ws2-gateway	aafe5c2a0d135940769723c681d6c250e961d162
feat/pr6b-chat-tool-loop-ui	7f0efeb9c002701a156c585833f42a44db210e4d
feat/pr6d-case-law-skill	1fbdb796d45269494dc9eabaead90d27e43bdffc
feat/research-search-cursor	986b7b5bc01c3caea8183f9bbd80db799f2b654e
feat/research-subsystem	1cddfbb44f511bb691dc1e5c0edbf4f4118d8e24
feat/tool-provider-admin-api	5fc0ed471b37504ed91b018128fc24e5ceabc5f6
feat/wsd-pr1-agentic-loop	b9060d7efd5fe654038fbcc2e04eb23b4bc5e28f
feat/wsd-pr2-ledger-gate	b145f787236263fb378c902eb93d3584623b0879
feat/wse-content-source-registry	c4b233140cd805ccaac6c844a4745ef994cf47f5
feat/wse-pr1-registry-govinfo	ee4715dbcd95ad9ff0e6455e9b811fdf96190dbd
feat/wsg-pr1-ui-treatment-trace	27f5d0a6afe6e5107d075c3c248a7dd92857a30a
fix/chat-receipts-inference-detail-fields	4aa7605d1d748722d1d97b7ad72d56eb93489fb5
fix/compose-forward-gateway-master-key	7b3cc30bc66c857ad9e2c75dd709387d2c698c2e
fix/de-305-bridge-compose-required-vars	5d47f637a395e2c4ec54188eec193bbfb21e0fcf
fix/donna-9-worker-skill-registry	7f0df5f4578706a83336ba02a04d4ca1da537430
fix/gpt5-max-completion-tokens	27f28e0e8e6bfde3ac43947866e93a436fc7dd79
fix/issue-99-local-profile-paddleocr	e2b69301aef66d25a019fca739cb0afc4c4809fb
fix/launcher-reverse-proxy	3a9d65456faee1f285ae0900c3ca7a9280afdf9f
fix/m3-e1-tabular-citations-version	81cb29e6b6214799c95da972144e44fdf4c64d22
fix/openapi-autonomous-decimal-as-string	131fa39a206419f9a3cd839f5973c380b979d50f
fix/openapi-autonomous-max-cost-drift	4131ba43d2b8e97d47ee1b0714a57d5b615aad39
fix/provider-4xx-not-outage-code	8d8b8261c66e2ebe67f7c4cd21af22916652a2c5
fix/release-sbom-ghcr-auth	caae6db6343be459de45ae898fb783b9b65cb88d
fix/release-sbom-no-release-assets	8b65d639c27fed85a5b0a5178a3835ed1e78ea79
fix/research-openapi-typed-shapes	63895486e8f779cf053dd989bd067406e2626e37
fix/streaming-routing-log-persist	2721100c73fc9fd70e647ee6b296ade9ca14ee66
fix/strip-lq-ai-privileged-file-ids	b09cfdfcb1b0ba33307f4a1296df0f42b8b89e39
handoff/2026-05-19-m3-a5-shipped-a6-kickoff	bc8800535c39308e18e709f33024a3887701137f
handoff/m3-phase-a-progress-a4-kickoff	69e92cc7de6561f8bb42c4aa50be8781d6309833
m2-d1-ensemble	5d40741f8fd2d3e85971551724b186e18cd29626
m2-d2-citation-anonymization	acbd61e48504082a64f5b1271579adb00d13e157
m2-d3-privileged-handling	18025cff9b0d763b6306596baeec5a06f0ca490e
m2-d4-edge-cases	4c786b0262e55a4c54b2c9831fbff8041c273f3f
m2-development	05b7da42a1195632107fc6462003ab2392d969fe
m2-docs-honest-state-update	bf1abe725a4f8f4441cbafbd3c9d60181b1ef250
m2/c3-anonymization-round-trip	a9aebcda01582f5289b2f7564fce147a6211ae44
m3-0-1-de-283-login-ux	610191022151fc9e2f5b2fe5ae21273c88a3b339
m3-0-2-de-277-citation-chunk-boundary	ec8fb776fd64eb76d1797cd81e7c412712742788
m3-0-3-de-276-ingest-observability	5e1e0d778356e6fee73bdfaaeb9877cc9d70b01c
m3-a1-playbook-schema	d642f2d8ebe59c364ea07c40f458c570460c6cdd
m3-a2-playbook-executor	3152518069259ee1fc66493f3d182c4595230f6e
m3-a3-nda-playbook	b4ea4f8b04232325f700d737e29106ba8e31ebc9
m3-a4-playbook-execution-ui	86fbbd8cf3e583926bb0d7f33f86534b037ec677
m3-a5-builtin-playbooks-msa-dpa	b4b5df7c036afbac1b1de310226b172654079a71
m3-a6-easy-playbook-wizard	1c3d250407030770df43f5c803464377c97f4026
m3-c4-tabular-export	2e74e75fec3c59e284592ea6029463a5eeddf1eb
m3-d1-slack-bridge	ecac49f1ceb415132adc1196d8241ac012f7a70f
m3-d3-teams-bridge	f1edc8bf74b4fc76a52de612c65039828cf461ac
m3-d4-admin-intake-bridges	4bd519adc10f56b6c8c8f10b03b1da71fdecfd03
m3-phase-b-word-addin-plumbing	1b49eb340355980b78cbd8d22048f6bd430c9330
m3-phase-c-tabular-review	f60bde80a5d950cf932c51bb449b2c9b8ffafdea
m3-phase-f-otel-deepening-plan	b7c7f7d6f3b964c76d5faeeaea51a623be4df7ac
roadmap-enhancements-boundary-registers	80e78e897d994d023de5cad784b5e7fdf4639166
session-handoff-2026-05-21-evening	d09f70485141973919769253f613c842a7133d3b
session-handoff-2026-05-21-night-m3-c1-shipped-c2-substrate	7be8aa7910a0eb157b87977318a987e4de2ce05c
sync/m3-a6-to-main	e901f8a0754b4dc1dc7c72a614b8ff4dfcff0213
BRANCHES

$EXECUTE || echo "(dry run — pass --execute to delete)"
echo "processed=$deleted skipped=$skipped already-gone=$gone"
