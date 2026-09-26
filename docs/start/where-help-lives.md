# Where to find help

Open **Learn** inside the app for feature walkthroughs — how to use Playbooks, what a tier badge means, how to author a skill. Use this site for installation, maintenance, data-handling questions, and the incident procedures below.

Once a deployment is running, the Learn tab in the top navigation is an interactive tour: a set of playgrounds — the count grows with releases, so this page does not fix it — walks through the architecture, the full request lifecycle, the five-tier inference model, what the model actually sees, where data lives, and how to author a skill, each one linking straight to the source file that implements what it shows (README "First steps after login"). Most of the current set is under **Learn → How It Works**, with the skill-authoring one under **How to Build**. That's deliberate: end-user help sits next to the product it explains, versioned with the release that ships it, rather than duplicated on a separate site that can drift out of sync.

If you're looking for a walkthrough of a feature and you're already signed in, check Learn before searching here.

## Help when you cannot sign in

Use the [Quickstart's troubleshooting section](../quickstart.md#troubleshooting) and the [Troubleshooting](../operate/troubleshooting.md) page for startup and password problems — including resetting a forgotten first-run admin password without touching any data. The key-replacement and security-reporting instructions below remain available here even when the app itself is unavailable.

## The one exception: incident procedures with professional-conduct consequences

A small set of situations carry a duty beyond "how do I use the product" — a leaked provider key, a security vulnerability you've found, a control that failed silently on privileged work. Those procedures live on this site, in the Operate and Trust sections, because they're read under time pressure by someone who may not be signed into the deployment that's the problem, and because the professional-conduct stakes (client notification, confidentiality, disclosure obligations) belong in a durable, citable place rather than inside an app session:

- Rotate a leaked provider key — revoke, replace, and evidence the blast radius. See the [Operate](../site/operate/index.md) section.
- Security disclosure — what to do with a vulnerability you've found, and where the line to the public tracker sits. See the [Trust centre](../site/trust/index.md), or [`SECURITY.md`](../../SECURITY.md) directly.

Learn is most useful once you can sign in and want a feature walkthrough.
