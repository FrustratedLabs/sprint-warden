#!/bin/sh
# Run the example projects and assert the expected outcomes (see run_all.py).
#   sh examples/run-all.sh                # every stack whose toolchain is installed
#   sh examples/run-all.sh pytest go      # just these
#   sh examples/run-all.sh --keep         # then browse them with `sprint ui`
set -eu
here=$(cd "$(dirname "$0")" && pwd)
py=$(command -v python3 || command -v python)
exec "$py" "$here/run_all.py" "$@"
