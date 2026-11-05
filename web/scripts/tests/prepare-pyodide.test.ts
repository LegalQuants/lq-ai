import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
	findLockedPackage,
	missingLockFiles,
	pinnedInstallSpec,
	pypiMetadataUrl
} from '../prepare-pyodide.js';

// A trimmed stand-in for the committed web/static/pyodide/pyodide-lock.json.
// The key spellings mirror the real file on purpose: most keys keep the PyPI
// spelling (`scikit-learn`), while the entries prepare-pyodide.js injects
// for PyPI-only packages use underscores (`mypy_extensions`).
const lockData = {
	info: {
		abi_version: '2026_0',
		arch: 'wasm32',
		platform: 'emscripten_5_0_3',
		python: '3.14.0'
	},
	packages: {
		black: {
			name: 'black',
			version: '26.5.1',
			file_name: 'black-26.5.1-py3-none-any.whl',
			install_dir: 'site',
			sha256: '0000000000000000000000000000000000000000000000000000000000000000',
			package_type: 'package',
			imports: ['black'],
			depends: []
		},
		mypy_extensions: {
			name: 'mypy_extensions',
			version: '1.1.0',
			file_name: 'mypy_extensions-1.1.0-py3-none-any.whl',
			install_dir: 'site',
			sha256: '1111111111111111111111111111111111111111111111111111111111111111',
			package_type: 'package',
			imports: ['mypy_extensions'],
			depends: []
		},
		'scikit-learn': {
			name: 'scikit-learn',
			version: '1.8.0',
			file_name: 'scikit_learn-1.8.0-cp314-cp314-pyemscripten_2026_0_wasm32.whl',
			install_dir: 'site',
			sha256: '2222222222222222222222222222222222222222222222222222222222222222',
			package_type: 'package',
			imports: ['sklearn'],
			depends: []
		}
	}
};

test('findLockedPackage matches the lock key spellings used in the real file', () => {
	assert.equal(findLockedPackage(lockData, 'black')?.version, '26.5.1');
	assert.equal(findLockedPackage(lockData, 'scikit-learn')?.version, '1.8.0');
	// The script lists this package as `mypy_extensions`, but a hyphenated
	// lookup must find the same entry (and vice versa).
	assert.equal(findLockedPackage(lockData, 'mypy-extensions')?.version, '1.1.0');
	assert.equal(findLockedPackage(lockData, 'not-a-package'), undefined);
	assert.equal(findLockedPackage(null, 'black'), undefined);
});

test('pinnedInstallSpec pins installs to the locked version (#675)', () => {
	assert.equal(pinnedInstallSpec(lockData, 'black'), 'black==26.5.1');
	assert.equal(pinnedInstallSpec(lockData, 'scikit-learn'), 'scikit-learn==1.8.0');
	// A package the lock does not record keeps the bare name.
	assert.equal(pinnedInstallSpec(lockData, 'not-a-package'), 'not-a-package');
	assert.equal(pinnedInstallSpec(null, 'black'), 'black');
});

test('pypiMetadataUrl asks PyPI for the locked version, not the latest (#675)', () => {
	assert.equal(pypiMetadataUrl(lockData, 'black'), 'https://pypi.org/pypi/black/26.5.1/json');
	assert.equal(
		pypiMetadataUrl(lockData, 'mypy_extensions'),
		'https://pypi.org/pypi/mypy_extensions/1.1.0/json'
	);
	// Only a package missing from the lock falls back to the latest endpoint.
	assert.equal(
		pypiMetadataUrl(lockData, 'not-a-package'),
		'https://pypi.org/pypi/not-a-package/json'
	);
});

test('missingLockFiles reports exactly the locked files absent from disk', () => {
	// Scoped to named packages: only their files are required to exist.
	assert.deepEqual(missingLockFiles(lockData, [], ['black', 'mypy_extensions']), [
		'black-26.5.1-py3-none-any.whl',
		'mypy_extensions-1.1.0-py3-none-any.whl'
	]);
	assert.deepEqual(
		missingLockFiles(lockData, ['black-26.5.1-py3-none-any.whl'], ['black', 'not-a-package']),
		[]
	);
	// Unscoped: every file the lock records.
	assert.deepEqual(missingLockFiles(lockData, []), [
		'black-26.5.1-py3-none-any.whl',
		'mypy_extensions-1.1.0-py3-none-any.whl',
		'scikit_learn-1.8.0-cp314-cp314-pyemscripten_2026_0_wasm32.whl'
	]);
	assert.deepEqual(
		missingLockFiles(lockData, [
			'black-26.5.1-py3-none-any.whl',
			'mypy_extensions-1.1.0-py3-none-any.whl',
			'scikit_learn-1.8.0-cp314-cp314-pyemscripten_2026_0_wasm32.whl',
			'pyodide-lock.json'
		]),
		[]
	);
	assert.deepEqual(missingLockFiles(null, []), []);
});
