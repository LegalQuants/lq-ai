/**
 * Update-needed overlay (M3-B8).
 *
 * Rendered when the version handshake reports that the installed add-in
 * version is outside the deployment's compatibility range. Sits ABOVE
 * the sign-in gate so an out-of-date add-in can't push the user through
 * an OAuth handshake that would fail at the next breaking-change API
 * call.
 *
 * Two flavors: `addin_outdated` (most common — operator needs to
 * redistribute a newer manifest via M365 Admin Center) and
 * `deployment_outdated` (rare — the operator is running an old
 * deployment that hasn't been updated to recognize this newer add-in).
 * The "unknown" branch (handshake failed entirely) renders a softer
 * informational banner inside the normal layout rather than blocking
 * the user — `App.tsx` handles that case separately.
 */
import React from "react";
import type { VersionInfo } from "../version";

type UpdateNeededOverlayProps = {
  info: VersionInfo;
};

export const UpdateNeededOverlay: React.FC<UpdateNeededOverlayProps> = ({
  info,
}) => {
  const { status, installed_version, handshake } = info;

  const heading =
    status === "addin_outdated"
      ? "Your LQ.AI add-in needs an update"
      : "This deployment needs an update";

  const body =
    status === "addin_outdated"
      ? "The installed add-in is older than this deployment accepts. Ask your LQ.AI admin to redistribute the latest manifest via Microsoft 365 Admin Center; once Word picks up the update you can re-open the task pane and sign in."
      : "The installed add-in is newer than this deployment recognizes. Ask your LQ.AI admin to update the deployment to the latest release, or roll the add-in back to the version this deployment expects.";

  return (
    <section className="lq-update-overlay" role="alert">
      <h2 className="lq-update-title">{heading}</h2>
      <p className="lq-update-body">{body}</p>
      <dl className="lq-update-versions">
        <div className="lq-update-row">
          <dt>Installed add-in</dt>
          <dd>{installed_version}</dd>
        </div>
        {handshake && (
          <>
            <div className="lq-update-row">
              <dt>Deployment</dt>
              <dd>{handshake.deployment_version}</dd>
            </div>
            <div className="lq-update-row">
              <dt>Compatible range</dt>
              <dd>
                {handshake.addin_min_compatible_version} –{" "}
                {handshake.addin_max_compatible_version}
              </dd>
            </div>
          </>
        )}
      </dl>
      <p className="lq-update-footnote">
        Quote these version numbers when you contact your LQ.AI admin.
      </p>
    </section>
  );
};
