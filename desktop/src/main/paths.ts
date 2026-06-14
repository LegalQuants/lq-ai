import { app } from 'electron'
import { join } from 'node:path'

/** Per-user app data dir (e.g. ~/Library/Application Support/LQ.AI). */
export const dataDir = (): string => app.getPath('userData')

/** Where we persist the encrypted config blob. */
export const configPath = (): string => join(dataDir(), 'config.enc')

/** The chmod-600 .env handed to docker compose (lives in app data, NOT the repo). */
export const envPath = (): string => join(dataDir(), '.env')

/**
 * The release compose file. Bundled into the app at build time under resources/.
 * In dev (electron-vite) it is read from the repo root.
 */
export const composeFilePath = (): string =>
	app.isPackaged
		? join(process.resourcesPath, 'docker-compose.release.yml')
		: join(app.getAppPath(), '..', 'docker-compose.release.yml')

// Distinct from the build-from-source dev stack (project "lq-ai") AND from a Donna
// launcher ("donna-desktop") so this launcher gets its OWN isolated volumes and never
// collides on volumes/ports. `-p` overrides the compose file's top-level `name:`
// (Part D gotcha #2: sharing the dev project name reuses the dev pgdata volume, whose
// Postgres password differs from the launcher's generated one → api auth-fail crash-loop).
export const PROJECT_NAME = 'lq-ai-desktop'
