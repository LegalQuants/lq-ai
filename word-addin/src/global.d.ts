/**
 * Compile-time globals injected by webpack's `DefinePlugin`.
 *
 * `__ADDIN_VERSION__` carries the add-in's package.json `version` field
 * into the bundle so the M3-B8 version handshake can compare it against
 * the deployment's compatibility range without an extra round-trip to
 * fetch its own version. See `webpack.config.js` for the wiring.
 */
declare const __ADDIN_VERSION__: string;
