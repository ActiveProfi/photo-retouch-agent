$Port = 8501
$Url = "http://127.0.0.1:$Port"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$App = Join-Path $ProjectRoot "app.py"

function Test-PortOpen {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $Port)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

if (-not (Test-Path $Python)) {
    Write-Host "Python .venv not found."
    Read-Host "Press Enter"
    exit 1
}

if (-not (Test-PortOpen)) {
    Write-Host "Starting agent at $Url ..."
    Start-Process -FilePath $Python `
        -ArgumentList "-m", "streamlit", "run", $App `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Minimized

    $waited = 0
    while (-not (Test-PortOpen) -and $waited -lt 60) {
        Start-Sleep -Seconds 1
        $waited++
    }
}

Start-Process $Url
