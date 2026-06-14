// afterAllArtifactBuild hook: notarize + staple each produced .dmg.
//
// electron-builder's native `notarize` notarizes only the .app inside; the .dmg is
// built afterward and is otherwise un-notarized, so opening the downloaded (quarantined)
// dmg trips Gatekeeper. dmg.sign (in electron-builder.yml) signs the dmg; this hook then
// submits it to notarytool and staples the ticket so the dmg-open step passes cleanly.
//
// No-op when Apple creds are absent (local unsigned `npm run dist` smoke builds).
const { execFileSync } = require('node:child_process')

exports.default = async function notarizeDmg(buildResult) {
	const { APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD, APPLE_TEAM_ID } = process.env
	const dmgs = (buildResult.artifactPaths || []).filter((p) => p.endsWith('.dmg'))
	if (dmgs.length === 0) return []
	if (!APPLE_ID || !APPLE_APP_SPECIFIC_PASSWORD || !APPLE_TEAM_ID) {
		console.log('Skipping DMG notarization — Apple creds not set.')
		return []
	}

	for (const dmg of dmgs) {
		console.log(`Notarizing DMG: ${dmg}`)
		execFileSync(
			'xcrun',
			[
				'notarytool',
				'submit',
				dmg,
				'--apple-id',
				APPLE_ID,
				'--password',
				APPLE_APP_SPECIFIC_PASSWORD,
				'--team-id',
				APPLE_TEAM_ID,
				'--wait'
			],
			{ stdio: 'inherit' }
		)
		console.log(`Stapling DMG: ${dmg}`)
		execFileSync('xcrun', ['stapler', 'staple', dmg], { stdio: 'inherit' })
	}

	return []
}
