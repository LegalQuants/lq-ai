import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { preparePyodide } from '../prepare-pyodide.js';
import committedLock from '../../static/pyodide/pyodide-lock.json';
import installedLock from '../../node_modules/pyodide/pyodide-lock.json';
import { version } from '../../node_modules/pyodide/package.json';

const lockFilename = 'pyodide-lock.json';
const digest = (value: string) => createHash('sha256').update(value).digest('hex');
const packages = Object.fromEntries(
	Object.entries(committedLock.packages).map(([name, entry]) => [
		name,
		{ ...entry, sha256: digest(entry.file_name) }
	])
);
const bundledPackages = Object.fromEntries(
	Object.keys(installedLock.packages).map((name) => [name, packages[name]])
);
const lockText = JSON.stringify({ ...committedLock, packages }, null, 2);

const registry = new Map(
	Object.entries(packages).map(([name, entry]) => [
		`https://pypi.org/pypi/${name.replace(/_/g, '-')}/${entry.version}/json`,
		entry
	])
);
const transitiveWheel = packages['python-dateutil'].file_name;
let directory: string;
let runtimeDirectory: string;
let outputDirectory: string;
let outputLock: string;

const fetchWheel = vi.fn(async (url: string) => {
	const metadata = registry.get(url);
	if (metadata) {
		return Response.json({
			urls: [
				{
					filename: metadata.file_name,
					digests: { sha256: metadata.sha256 },
					url: `https://files.pythonhosted.org/${metadata.file_name}`
				}
			]
		});
	}
	return new Response(url.split('/').at(-1));
});

beforeEach(async () => {
	directory = await mkdtemp(join(tmpdir(), 'pyodide-prepare-'));
	runtimeDirectory = join(directory, 'runtime');
	outputDirectory = join(directory, 'output');
	outputLock = join(outputDirectory, lockFilename);
	await mkdir(runtimeDirectory);
	await mkdir(outputDirectory);
	await writeFile(outputLock, lockText);
	await writeFile(join(runtimeDirectory, 'package.json'), JSON.stringify({ version }));
	await writeFile(
		join(runtimeDirectory, lockFilename),
		JSON.stringify({ ...installedLock, packages: bundledPackages })
	);
	fetchWheel.mockClear();
	vi.stubGlobal('fetch', fetchWheel);
	vi.spyOn(console, 'log').mockImplementation(() => {});
});

afterEach(async () => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	await rm(directory, { recursive: true, force: true });
});

test('preparation preserves the lock and restores an absent transitive wheel', async () => {
	await preparePyodide({ runtimeDirectory, outputDirectory });
	const inventory = await readdir(outputDirectory);
	for (const name of ['seaborn', 'openpyxl', 'et-xmlfile', 'python-dateutil']) {
		expect(inventory).toContain(packages[name].file_name);
	}
	expect(await readFile(outputLock, 'utf8')).toBe(lockText);

	fetchWheel.mockClear();
	await rm(join(outputDirectory, transitiveWheel));
	await preparePyodide({ runtimeDirectory, outputDirectory });
	expect(fetchWheel.mock.calls).toEqual([
		[`https://cdn.jsdelivr.net/pyodide/v${version}/full/${transitiveWheel}`]
	]);
	expect(await readdir(outputDirectory)).toEqual(inventory);
	expect(await readFile(outputLock, 'utf8')).toBe(lockText);
});

test('stale runtime cleanup preserves the lock and replaces generated files', async () => {
	await writeFile(join(outputDirectory, 'package.json'), JSON.stringify({ version: 'old' }));
	await writeFile(join(outputDirectory, 'stale-wheel.whl'), 'old');
	await preparePyodide({ runtimeDirectory, outputDirectory });
	expect(await readdir(outputDirectory)).not.toContain('stale-wheel.whl');
	expect(await readFile(join(outputDirectory, 'package.json'), 'utf8')).toBe(
		JSON.stringify({ version })
	);
	expect(await readFile(outputLock, 'utf8')).toBe(lockText);
});

test('an incompatible lock fails before cache cleanup or downloads', async () => {
	const incompatibleLock = JSON.stringify({
		...committedLock,
		info: { ...committedLock.info, python: '3.13.0' }
	});
	await writeFile(outputLock, incompatibleLock);
	await writeFile(join(outputDirectory, 'package.json'), JSON.stringify({ version: 'old' }));
	await expect(preparePyodide({ runtimeDirectory, outputDirectory })).rejects.toThrow(
		'Pyodide lock python does not match installed runtime'
	);
	expect(fetchWheel).not.toHaveBeenCalled();
	expect(await readFile(join(outputDirectory, 'package.json'), 'utf8')).toBe(
		JSON.stringify({ version: 'old' })
	);
	expect(await readFile(outputLock, 'utf8')).toBe(incompatibleLock);
});

test('a failed required wheel download rejects preparation and preserves the lock', async () => {
	vi.stubGlobal('fetch', async (url: string) =>
		url.endsWith(`/${transitiveWheel}`) ? new Response(null, { status: 503 }) : fetchWheel(url)
	);
	await expect(preparePyodide({ runtimeDirectory, outputDirectory })).rejects.toThrow(
		`${transitiveWheel} download returned HTTP 503`
	);
	expect(await readdir(outputDirectory)).not.toContain(transitiveWheel);
	expect(await readdir(outputDirectory)).not.toContain('package.json');
	expect(await readFile(outputLock, 'utf8')).toBe(lockText);
});

test('a different wheel filename cannot satisfy a pinned PyPI entry', async () => {
	const entry = packages.openpyxl;
	vi.stubGlobal('fetch', async (url: string) => {
		expect(url).toBe(`https://pypi.org/pypi/openpyxl/${entry.version}/json`);
		return Response.json({
			urls: [{ filename: 'other-py3-none-any.whl', digests: { sha256: entry.sha256 } }]
		});
	});
	await expect(preparePyodide({ runtimeDirectory, outputDirectory })).rejects.toThrow(
		`PyPI is missing the locked wheel ${entry.file_name}`
	);
	expect(await readdir(outputDirectory)).toEqual([lockFilename]);
});
