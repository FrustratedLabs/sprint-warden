# Run the example projects and assert the expected outcomes (see run_all.py).
#   pwsh examples/run-all.ps1                # every stack whose toolchain is installed
#   pwsh examples/run-all.ps1 pytest go      # just these
#   pwsh examples/run-all.ps1 --keep         # then browse them with `sprint ui`
$ErrorActionPreference = "Stop"
$python = (Get-Command python -ErrorAction SilentlyContinue) ?? (Get-Command py -ErrorAction SilentlyContinue) ?? (Get-Command python3)
& $python.Source (Join-Path $PSScriptRoot "run_all.py") @args
exit $LASTEXITCODE
