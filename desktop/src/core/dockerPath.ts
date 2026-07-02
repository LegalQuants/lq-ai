// A macOS app launched from Finder/Applications inherits a minimal PATH
// (/usr/bin:/bin:/usr/sbin:/sbin) that omits the directories where the `docker`
// CLI actually lives — so a bare `spawn('docker')` fails with ENOENT even when
// Docker Desktop is installed. We prepend the known docker bin dirs to PATH.

/** Standard locations the `docker` CLI is installed to on macOS. */
export const DOCKER_BIN_DIRS = [
	'/usr/local/bin', // Docker Desktop CLI symlink (Intel + Apple Silicon)
	'/opt/homebrew/bin', // Homebrew on Apple Silicon
	'/Applications/Docker.app/Contents/Resources/bin' // Docker Desktop bundled CLI
]

/**
 * Merge a base PATH with the known docker bin dirs. Extra dirs come first so a
 * Finder-launched app can find `docker`; entries are de-duplicated, order preserved.
 * Pure: the caller passes process.env.PATH.
 */
export function dockerSearchPath(currentPath = '', extraDirs: string[] = DOCKER_BIN_DIRS): string {
	const seen = new Set<string>()
	const out: string[] = []
	for (const dir of [...extraDirs, ...currentPath.split(':')]) {
		if (dir && !seen.has(dir)) {
			seen.add(dir)
			out.push(dir)
		}
	}
	return out.join(':')
}
