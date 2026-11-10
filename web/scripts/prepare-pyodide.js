const packages = [
	'micropip',
	'packaging',
	'requests',
	'beautifulsoup4',
	'numpy',
	'pandas',
	'matplotlib',
	'scikit-learn',
	'scipy',
	'regex',
	'sympy',
	'tiktoken',
	'seaborn',
	'pytz',
	'black',
	'openai',
	'openpyxl'
];

import { createHash, randomUUID } from 'node:crypto';
import { copyFile, readFile, readdir, rename, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { setGlobalDispatcher, ProxyAgent } from 'undici';

const lockFilename = 'pyodide-lock.json';
const normalize = (name) => name.toLowerCase().replace(/[-_.]+/g, '-');
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
const readJson = async (path) => JSON.parse(await readFile(path, 'utf8'));

/**
 * Loading network proxy configurations from the environment variables.
 * And the proxy config with lowercase name has the highest priority to use.
 */
function initNetworkProxyFromEnv() {
	// we assume all subsequent requests in this script are HTTPS:
	// https://cdn.jsdelivr.net
	// https://pypi.org
	// https://files.pythonhosted.org
	const allProxy = process.env.all_proxy || process.env.ALL_PROXY;
	const httpsProxy = process.env.https_proxy || process.env.HTTPS_PROXY;
	const httpProxy = process.env.http_proxy || process.env.HTTP_PROXY;
	const preferedProxy = httpsProxy || allProxy || httpProxy;
	/**
	 * use only http(s) proxy because socks5 proxy is not supported currently:
	 * @see https://github.com/nodejs/undici/issues/2224
	 */
	if (!preferedProxy || !preferedProxy.startsWith('http')) return;
	let preferedProxyURL;
	try {
		preferedProxyURL = new URL(preferedProxy).toString();
	} catch {
		console.warn(`Invalid network proxy URL: "${preferedProxy}"`);
		return;
	}
	const dispatcher = new ProxyAgent({ uri: preferedProxyURL });
	setGlobalDispatcher(dispatcher);
	console.log(`Initialized network proxy "${preferedProxy}" from env`);
}

function lockedWheels(lock, runtimeLock, version) {
	for (const key of ['abi_version', 'arch', 'platform', 'python']) {
		if (!lock.info?.[key] || lock.info[key] !== runtimeLock.info?.[key]) {
			throw new Error(`Pyodide lock ${key} does not match installed runtime ${version}`);
		}
	}

	const entries = new Map(
		Object.entries(lock.packages).map(([name, entry]) => [normalize(name), entry])
	);
	const runtimeEntries = new Map(
		Object.entries(runtimeLock.packages).map(([name, entry]) => [normalize(name), entry])
	);
	const wheels = new Map();
	const pending = [...packages];
	while (pending.length) {
		const name = normalize(pending.pop());
		if (wheels.has(name)) continue;

		const entry = entries.get(name);
		if (
			!entry?.version ||
			!/^[\w.-]+\.whl$/.test(entry.file_name) ||
			!/^[a-f0-9]{64}$/.test(entry.sha256) ||
			!Array.isArray(entry.depends)
		) {
			throw new Error(`Missing or invalid Pyodide lock entry for ${name}`);
		}

		const bundled = runtimeEntries.get(name);
		if (bundled) {
			if (
				bundled.version !== entry.version ||
				bundled.file_name !== entry.file_name ||
				bundled.sha256 !== entry.sha256
			) {
				throw new Error(`Locked ${name} does not match Pyodide ${version}'s wheel`);
			}
		} else if (!/-(?:py2\.)?py3-none-any\.whl$/.test(entry.file_name)) {
			throw new Error(`Locked ${name} is not a pure Python wheel for Pyodide ${version}`);
		}

		wheels.set(name, { entry, bundled });
		pending.push(...entry.depends);
	}
	return wheels;
}

async function wheelUrl(name, entry, bundled, version) {
	if (bundled) return `https://cdn.jsdelivr.net/pyodide/v${version}/full/${entry.file_name}`;

	const response = await fetch(
		`https://pypi.org/pypi/${encodeURIComponent(name)}/${encodeURIComponent(entry.version)}/json`
	);
	if (!response.ok) throw new Error(`PyPI metadata for ${name} returned HTTP ${response.status}`);

	const { urls } = await response.json();
	const wheel = urls?.find(
		(file) => file.filename === entry.file_name && file.digests?.sha256 === entry.sha256
	);
	if (!wheel) throw new Error(`PyPI is missing the locked wheel ${entry.file_name}`);
	return wheel.url;
}

async function ensureWheel(directory, name, entry, bundled, version) {
	const path = join(directory, entry.file_name);
	try {
		if (sha256(await readFile(path)) === entry.sha256) return;
	} catch (err) {
		if (err.code !== 'ENOENT') throw err;
	}

	console.log(`Downloading ${entry.file_name}`);
	const response = await fetch(await wheelUrl(name, entry, bundled, version));
	if (!response.ok) throw new Error(`${entry.file_name} download returned HTTP ${response.status}`);

	const bytes = Buffer.from(await response.arrayBuffer());
	if (sha256(bytes) !== entry.sha256) throw new Error(`SHA-256 mismatch for ${entry.file_name}`);

	const temporaryPath = `${path}.${randomUUID()}.tmp`;
	try {
		await writeFile(temporaryPath, bytes);
		await rename(temporaryPath, path);
	} finally {
		await rm(temporaryPath, { force: true });
	}
}

export async function preparePyodide({
	runtimeDirectory = 'node_modules/pyodide',
	outputDirectory = 'static/pyodide'
} = {}) {
	const [lock, runtimeLock, { version }] = await Promise.all([
		readJson(join(outputDirectory, lockFilename)),
		readJson(join(runtimeDirectory, lockFilename)),
		readJson(join(runtimeDirectory, 'package.json'))
	]);
	const wheels = lockedWheels(lock, runtimeLock, version);

	const cachedRuntime = await readJson(join(outputDirectory, 'package.json')).catch((err) => {
		if (err.code !== 'ENOENT') throw err;
		return null;
	});
	if (cachedRuntime && cachedRuntime.version !== version) {
		console.log('Pyodide version mismatch, removing generated cache files');
		for (const entry of await readdir(outputDirectory)) {
			if (entry === lockFilename) continue;
			await rm(join(outputDirectory, entry), { recursive: true, force: true });
		}
	}

	for (const [name, { entry, bundled }] of wheels) {
		await ensureWheel(outputDirectory, name, entry, bundled, version);
	}

	for (const entry of await readdir(runtimeDirectory, { withFileTypes: true })) {
		if (!entry.isFile() || entry.name === lockFilename) continue;
		await copyFile(join(runtimeDirectory, entry.name), join(outputDirectory, entry.name));
	}
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
	initNetworkProxyFromEnv();
	await preparePyodide();
}
