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

// Pure-Python packages whose wheels must be downloaded from PyPI and saved into
// static/pyodide/ so that the browser can install them offline via micropip.
// Packages already provided by the Pyodide distribution (click, platformdirs,
// typing_extensions, etc.) do NOT need to be listed here.
const pypiPackages = ['black', 'pathspec', 'mypy_extensions', 'pytokens'];

import { loadPyodide } from 'pyodide';
import { setGlobalDispatcher, ProxyAgent } from 'undici';
import { writeFile, readFile, copyFile, readdir, rm, access } from 'fs/promises';
import { pathToFileURL } from 'url';

const lockFilePath = 'static/pyodide/pyodide-lock.json';

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

/**
 * The committed pyodide-lock.json is the source of truth for package
 * versions (#675). Lock keys are not normalized consistently — most keep
 * the PyPI spelling (`scikit-learn`) while entries injected by this script
 * use underscores (`mypy_extensions`) — so lookups compare a normalized
 * form of both sides.
 */
export function findLockedPackage(lockData, packageName) {
	if (!lockData || !lockData.packages) return undefined;
	const normalize = (name) => name.toLowerCase().replace(/[-_.]+/g, '_');
	const wanted = normalize(packageName);
	for (const [key, entry] of Object.entries(lockData.packages)) {
		if (normalize(key) === wanted) return entry;
	}
	return undefined;
}

/**
 * The micropip install spec for a package: pinned to the version recorded
 * in the committed lock when there is one, the bare name otherwise.
 */
export function pinnedInstallSpec(lockData, packageName) {
	const entry = findLockedPackage(lockData, packageName);
	return entry && entry.version ? `${packageName}==${entry.version}` : packageName;
}

/**
 * The PyPI metadata URL for a package: the version-specific endpoint for
 * the locked version when the lock pins one, so a build never resolves
 * whatever happens to be the latest release that day. The unversioned
 * endpoint is only used for a package the lock does not record yet.
 */
export function pypiMetadataUrl(lockData, packageName) {
	const entry = findLockedPackage(lockData, packageName);
	return entry && entry.version
		? `https://pypi.org/pypi/${packageName}/${entry.version}/json`
		: `https://pypi.org/pypi/${packageName}/json`;
}

/**
 * The `file_name`s recorded in the lock that are not in `presentFiles`
 * (the current listing of static/pyodide/). When `packageNames` is given,
 * only those packages are considered — the lock records the whole Pyodide
 * distribution, but this script only ever downloads the packages it
 * installs plus the PyPI wheels below, so only their files can be
 * required to exist.
 */
export function missingLockFiles(lockData, presentFiles, packageNames) {
	if (!lockData || !lockData.packages) return [];
	const present = new Set(presentFiles);
	const entries = packageNames
		? packageNames
				.map((name) => findLockedPackage(lockData, name))
				.filter((entry) => entry !== undefined)
		: Object.values(lockData.packages);
	return entries
		.map((entry) => entry.file_name)
		.filter((fileName) => fileName && !present.has(fileName));
}

async function readLockFile() {
	try {
		return JSON.parse(await readFile(lockFilePath, 'utf-8'));
	} catch {
		return null;
	}
}

async function fileExists(path) {
	try {
		await access(path);
		return true;
	} catch {
		return false;
	}
}

async function downloadPackages() {
	console.log('Setting up pyodide + micropip');

	// Read the committed lock before anything touches static/pyodide: it
	// decides both whether a download is needed at all and which versions
	// to ask for.
	const committedLock = await readLockFile();

	const packageJson = JSON.parse(await readFile('package.json'));
	const pyodideVersion = packageJson.dependencies.pyodide.replace('^', '');

	let lockUsable = committedLock !== null;
	try {
		const pyodidePackageJson = JSON.parse(await readFile('static/pyodide/package.json'));
		const pyodidePackageVersion = pyodidePackageJson.version.replace('^', '');

		if (pyodideVersion !== pyodidePackageVersion) {
			console.log('Pyodide version mismatch, removing generated cache files');
			for (const entry of await readdir('static/pyodide')) {
				if (entry === 'pyodide-lock.json') continue;
				await rm(`static/pyodide/${entry}`, { recursive: true, force: true });
			}
		}
	} catch (err) {
		console.log('Pyodide package not found, proceeding with download.', err);
	}

	if (lockUsable) {
		const presentFiles = await readdir('static/pyodide').catch(() => []);
		const missing = missingLockFiles(committedLock, presentFiles, [...packages, ...pypiPackages]);
		if (missing.length === 0) {
			console.log(
				'All files recorded in pyodide-lock.json for the build packages ' +
					'are already present, skipping download'
			);
			return;
		}
		console.log(
			`${missing.length} file(s) recorded in pyodide-lock.json are missing, ` +
				'downloading the pinned versions'
		);
	}

	let pyodide;
	try {
		pyodide = await loadPyodide({
			packageCacheDir: 'static/pyodide'
		});
	} catch (err) {
		console.error('Failed to load Pyodide:', err);
		return;
	}

	try {
		console.log('Loading micropip package');
		await pyodide.loadPackage('micropip');

		const micropip = pyodide.pyimport('micropip');
		console.log('Downloading Pyodide packages:', packages);

		try {
			for (const pkg of packages) {
				const spec = pinnedInstallSpec(lockUsable ? committedLock : null, pkg);
				console.log(`Installing package: ${spec}`);
				await micropip.install(spec);
			}
		} catch (err) {
			console.error('Package installation failed:', err);
			return;
		}

		console.log('Pyodide packages downloaded, freezing into lock file');

		try {
			if (lockUsable) {
				// The installs above were pinned by the committed lock, so a
				// fresh freeze has nothing to add — and rewriting the tracked
				// file from a live resolve is what made builds leave the
				// working tree dirty (#675). Leave it byte-identical.
				console.log('Keeping the committed pyodide-lock.json unchanged');
			} else {
				const lockFile = await micropip.freeze();
				await writeFile(lockFilePath, lockFile);
			}
		} catch (err) {
			console.error('Failed to write lock file:', err);
		}
	} catch (err) {
		console.error('Failed to load or install micropip:', err);
	}
}

async function copyPyodide() {
	console.log('Copying Pyodide files into static directory');
	// Copy all files from node_modules/pyodide to static/pyodide — except the
	// distribution's own lock file, which must never overwrite the committed
	// one (#675).
	for await (const entry of await readdir('node_modules/pyodide')) {
		if (entry === 'pyodide-lock.json') continue;
		await copyFile(`node_modules/pyodide/${entry}`, `static/pyodide/${entry}`);
	}
}

/**
 * Download pure-Python wheels from PyPI and save them into static/pyodide/.
 * Also injects entries into pyodide-lock.json so that micropip resolves these
 * packages from the local server instead of fetching them from the internet.
 *
 * Versions come from the committed lock, never from PyPI's latest release:
 * a package the lock already pins is fetched (if its wheel is missing) via
 * the version-specific metadata endpoint, and the lock file is only
 * rewritten when a package is genuinely new to it (#675).
 */
async function downloadPyPIWheels() {
	let lockData;
	try {
		lockData = JSON.parse(await readFile(lockFilePath, 'utf-8'));
	} catch {
		console.warn('Could not read pyodide-lock.json, skipping PyPI wheel download');
		return;
	}

	let lockChanged = false;

	for (const pkg of pypiPackages) {
		const lockedEntry = findLockedPackage(lockData, pkg);

		// Locked and already downloaded: no network access at all.
		if (
			lockedEntry &&
			lockedEntry.file_name &&
			(await fileExists(`static/pyodide/${lockedEntry.file_name}`))
		) {
			console.log(`  Already exists: ${lockedEntry.file_name}`);
			continue;
		}

		console.log(`Fetching PyPI metadata for: ${pkg}`);
		const res = await fetch(pypiMetadataUrl(lockData, pkg));
		if (!res.ok) {
			console.error(`Failed to fetch PyPI metadata for ${pkg}: ${res.status}`);
			continue;
		}
		const meta = await res.json();
		const version = meta.info.version;
		const files = meta.urls || [];
		// Prefer the exact wheel the lock records; fall back to any
		// pure-Python wheel (py3-none-any).
		const wheel =
			files.find((f) => lockedEntry && f.filename === lockedEntry.file_name) ||
			files.find((f) => f.filename.endsWith('.whl') && f.filename.includes('py3-none-any'));
		if (!wheel) {
			console.warn(`No pure-Python wheel found for ${pkg}==${version}, skipping`);
			continue;
		}
		const dest = `static/pyodide/${wheel.filename}`;
		// Download wheel if not already present
		try {
			await access(dest);
			console.log(`  Already exists: ${wheel.filename}`);
		} catch {
			console.log(`  Downloading: ${wheel.filename}`);
			const wheelRes = await fetch(wheel.url);
			if (!wheelRes.ok) {
				console.error(`  Failed to download ${wheel.filename}: ${wheelRes.status}`);
				continue;
			}
			const buffer = Buffer.from(await wheelRes.arrayBuffer());
			await writeFile(dest, buffer);
			console.log(`  Saved: ${dest} (${buffer.length} bytes)`);
		}

		// Inject into pyodide-lock.json so micropip resolves locally
		const normalizedName = pkg.replace(/-/g, '_');
		if (!lockData.packages[normalizedName]) {
			lockData.packages[normalizedName] = {
				name: normalizedName,
				version: version,
				file_name: wheel.filename,
				install_dir: 'site',
				sha256: wheel.digests?.sha256 || '',
				package_type: 'package',
				imports: [normalizedName],
				depends: []
			};
			lockChanged = true;
			console.log(`  Added ${normalizedName}==${version} to pyodide-lock.json`);
		}
	}

	if (lockChanged) {
		await writeFile(lockFilePath, JSON.stringify(lockData, null, 2));
		console.log('Updated pyodide-lock.json with PyPI packages');
	} else {
		console.log('pyodide-lock.json unchanged');
	}
}

// Run only when executed directly (`npm run pyodide:fetch`), not when the
// module is imported by the unit tests in scripts/tests/.
const isMainModule = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;

if (isMainModule) {
	initNetworkProxyFromEnv();
	await downloadPackages();
	await copyPyodide();
	await downloadPyPIWheels();
}
