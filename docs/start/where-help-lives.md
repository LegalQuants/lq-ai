# Where help lives

This site is not the help desk for a running deployment. If your question is "how do I use Playbooks," "what does this tier badge mean," "how do I author a skill," or anything else about operating the product day to day, the answer lives inside the application itself, not here — and this page exists so you stop searching the docs site for it and go find it in the right place instead.

## The in-app Learn surface is the front door

Once a deployment is running, the **Learn** tab in the top navigation is an interactive tour: eleven playgrounds walk through the architecture, the full request lifecycle, the five-tier inference model, what the model actually sees, where data lives, and how to author a skill — each one linking straight to the source file that implements what it shows (README "First steps after login"). That is deliberate: end-user help sits next to the product it explains, versioned with the release that ships it, rather than duplicated on a separate site that can drift out of sync.

This site does not attempt to duplicate that surface. If you're looking for a walkthrough of a feature and you're already signed in, check Learn before searching here.

## The one exception: incident procedures with professional-conduct consequences

A small set of situations carry a duty beyond "how do I use the product" — a leaked provider key, a security vulnerability you've found, a control that failed silently on privileged work. Those procedures live on this site, in the Operate and Trust sections, because they're read under time pressure by someone who may not be signed into the deployment that's the problem, and because the professional-conduct stakes (client notification, confidentiality, disclosure obligations) belong in a durable, citable place rather than inside an app session:

- Rotate a leaked provider key — revoke, replace, and evidence the blast radius. See the [Operate](../site/operate/index.md) section.
- Security disclosure — what to do with a vulnerability you've found, and where the line to the public tracker sits. See the [Trust centre](../site/trust/index.md), or [`SECURITY.md`](../../SECURITY.md) directly.
