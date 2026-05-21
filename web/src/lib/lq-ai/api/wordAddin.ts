/**
 * Word add-in admin API client (M3-B1).
 *
 * Surface (current):
 *
 *   - GET /api/v1/admin/word-addin/manifest — admin-only. Returns the
 *     rendered Office Add-in XML manifest with the operator's deployment
 *     URL + a freshly generated GUID substituted. Operators sideload
 *     the file via Microsoft 365 Admin Center.
 *
 * Per PRD §9 DE-287, the Word add-in's in-task-pane feature surfaces
 * (chat / skills / playbook execution / Inference Tier badge) are
 * descoped to M4 / community contribution; this M3-B1 client ships the
 * install-side plumbing only.
 */
import { apiRequest } from './client';

export interface WordAddinManifestOptions {
	/** Override the deployment origin embedded in the manifest. Defaults
	 *  to the request's effective origin (reverse-proxy aware). */
	deploymentOrigin?: string;
	/** Branded name surfaced inside Word's ribbon and the task pane
	 *  GetStarted message. Defaults to "LQ.AI". */
	displayName?: string;
	/** ProviderName value the manifest surfaces to Microsoft 365 Admin
	 *  Center. Defaults to "LegalQuants". */
	providerName?: string;
}

export interface WordAddinManifestResult {
	xml: string;
	filename: string;
}

const DEFAULT_FILENAME = 'lq-ai-word-addin-manifest.xml';

/** Fetch a rendered Word add-in manifest from the backend. Reuses the
 *  project-wide apiRequest helper so the call gets auth header attachment
 *  + 401 refresh-and-retry without re-implementing those concerns here.
 */
export async function fetchWordAddinManifest(
	options: WordAddinManifestOptions = {}
): Promise<WordAddinManifestResult> {
	const params = new URLSearchParams();
	if (options.deploymentOrigin) {
		params.set('deployment_origin', options.deploymentOrigin);
	}
	if (options.displayName) {
		params.set('display_name', options.displayName);
	}
	if (options.providerName) {
		params.set('provider_name', options.providerName);
	}

	const query = params.toString();
	const path = `/admin/word-addin/manifest${query ? `?${query}` : ''}`;

	const xml = await apiRequest<string>(path, {
		method: 'GET',
		accept: 'application/xml'
	});

	return { xml, filename: DEFAULT_FILENAME };
}

/** Trigger a browser download of the rendered manifest. */
export function downloadManifestFile(result: WordAddinManifestResult): void {
	const blob = new Blob([result.xml], { type: 'application/xml' });
	const url = URL.createObjectURL(blob);
	try {
		const anchor = document.createElement('a');
		anchor.href = url;
		anchor.download = result.filename;
		document.body.appendChild(anchor);
		anchor.click();
		document.body.removeChild(anchor);
	} finally {
		// Revoke after the click so the download has a chance to start.
		setTimeout(() => URL.revokeObjectURL(url), 1000);
	}
}
