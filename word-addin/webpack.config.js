/* eslint-env node */
/**
 * webpack config for the LQ.AI Word add-in.
 *
 * Produces:
 *   dist/taskpane.html        — task pane shell loaded by Office.js
 *   dist/taskpane.bundle.js   — React 18 + TypeScript task pane
 *   dist/commands.html        — ribbon command surface
 *   dist/commands.bundle.js   — Office.js command handlers
 *   dist/manifest.xml         — manifest copied as-is (templated at install time
 *                                by the LQ.AI admin UI; see M3-B1 backend endpoint).
 *   dist/assets/...           — icons referenced by manifest.xml
 *
 * Per Phase B Decision B-1 (2026-05-21 prep doc): webpack is the bundler of
 * record — matches Office Add-in CLI's default toolchain and the documentation
 * Microsoft ships for new add-in projects.
 */

const path = require("path");
const webpack = require("webpack");
const HtmlWebpackPlugin = require("html-webpack-plugin");
const CopyWebpackPlugin = require("copy-webpack-plugin");
const pkg = require("./package.json");

module.exports = (env, argv) => {
  const isProduction = argv.mode === "production";

  return {
    devtool: isProduction ? "source-map" : "eval-source-map",
    entry: {
      taskpane: path.resolve(__dirname, "src/taskpane/taskpane.tsx"),
      commands: path.resolve(__dirname, "src/commands/commands.ts"),
    },
    output: {
      // Build outputs land in the SvelteKit static directory so the existing
      // web container serves them at `<origin>/word-addin/` without any
      // additional routing logic. This is the M3-B1 path; M3-B8 may move
      // this behind a versioned bundle endpoint when the deployment-served
      // bundle + version-handshake protocol lands.
      path: path.resolve(__dirname, "..", "web", "static", "word-addin"),
      filename: "[name].bundle.js",
      clean: true,
    },
    resolve: {
      extensions: [".ts", ".tsx", ".js", ".jsx"],
      alias: {
        "@": path.resolve(__dirname, "src"),
      },
    },
    module: {
      rules: [
        {
          test: /\.tsx?$/,
          use: "ts-loader",
          exclude: /node_modules/,
        },
        {
          test: /\.css$/,
          use: ["style-loader", "css-loader"],
        },
        {
          test: /\.html$/,
          use: "html-loader",
          exclude: [
            path.resolve(__dirname, "src/taskpane/taskpane.html"),
            path.resolve(__dirname, "src/commands/commands.html"),
          ],
        },
        {
          test: /\.(png|svg|jpg|jpeg|gif)$/i,
          type: "asset/resource",
          generator: { filename: "assets/[name][ext]" },
        },
      ],
    },
    plugins: [
      // Inject the package.json version into the bundle as the
      // ``__ADDIN_VERSION__`` global. M3-B8's version handshake compares
      // this value against the deployment's compatibility range — bake
      // it in at build time so the runtime check can't be tricked by a
      // tampered API response.
      new webpack.DefinePlugin({
        __ADDIN_VERSION__: JSON.stringify(pkg.version),
      }),
      new HtmlWebpackPlugin({
        filename: "taskpane.html",
        template: path.resolve(__dirname, "src/taskpane/taskpane.html"),
        chunks: ["taskpane"],
      }),
      new HtmlWebpackPlugin({
        filename: "commands.html",
        template: path.resolve(__dirname, "src/commands/commands.html"),
        chunks: ["commands"],
      }),
      new CopyWebpackPlugin({
        patterns: [
          { from: "manifest.xml", to: "manifest.xml" },
          { from: "assets", to: "assets" },
        ],
      }),
    ],
    devServer: {
      static: {
        directory: path.resolve(__dirname, "..", "web", "static", "word-addin"),
      },
      port: 3001,
      https: true,
      headers: { "Access-Control-Allow-Origin": "*" },
    },
  };
};
