$ErrorActionPreference = 'Stop'

$checks = @(
    @{ Name = 'DevAtlas'; Url = 'http://127.0.0.1:8000/health' },
    @{ Name = 'Incident Agent'; Url = 'http://127.0.0.1:8001/health' },
    @{ Name = 'Incident Agent Web'; Url = 'http://127.0.0.1:5174/' }
)

foreach ($check in $checks) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -SkipHttpErrorCheck $check.Url
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
            Write-Output "[OK] $($check.Name): $($response.StatusCode)"
        } else {
            Write-Output "[FAIL] $($check.Name): $($response.StatusCode)"
        }
    } catch {
        Write-Output "[FAIL] $($check.Name): unavailable"
    }
}
