param(
    [string]$AdapterPath = "",
    [ValidateSet("auto", "cpu", "cuda:0", "cuda:1")]
    [string]$NluDevice = "auto",
    [ValidateSet("mock", "whisper")]
    [string]$Stt = "mock",
    [ValidateSet("mock", "melo", "qwen3")]
    [string]$Tts = "mock",
    [int]$Port = 8000,
    [switch]$ValidateOnly
)

$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $AdapterPath) {
    $AdapterPath = Join-Path $projectRoot "models\nlu\qwen3-1.7b-mallo-v2"
}
$adapterConfig = Join-Path $AdapterPath "adapter_config.json"
$adapterWeights = Get-ChildItem -LiteralPath $AdapterPath -Filter "adapter_model.*" -ErrorAction SilentlyContinue
if (-not (Test-Path -LiteralPath $adapterConfig -PathType Leaf) -or -not $adapterWeights) {
    throw "Qwen NLU final-adapter를 찾지 못했습니다: $AdapterPath"
}
if ($ValidateOnly) {
    Write-Output "Qwen NLU adapter 확인 완료: $AdapterPath"
    exit 0
}

$env:PYTHONPATH = Join-Path $projectRoot "src"
$env:PYTHONUTF8 = "1"
Set-Location -LiteralPath $projectRoot

python -m app.server `
    --host 127.0.0.1 `
    --port $Port `
    --nlu qwen `
    --nlu-adapter $AdapterPath `
    --nlu-device $NluDevice `
    --stt $Stt `
    --tts $Tts
