#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

# The frontend uses ONNX in the browser, not Node's CUDA provider. Keep all
# frontend installs independent of the optional GPU archive on GitHub.
export ONNXRUNTIME_NODE_INSTALL_CUDA=skip
exec npm ci "$@"
