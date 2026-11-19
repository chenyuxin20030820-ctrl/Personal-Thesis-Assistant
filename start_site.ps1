$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Python virtual environment not found: $pythonExe"
}

# A running site does not need another server process.
$client = [System.Net.Sockets.TcpClient]::new()
try {
    $result = $client.BeginConnect('127.0.0.1', 8000, $null, $null)
    if ($result.AsyncWaitHandle.WaitOne(500)) {
        try {
            $client.EndConnect($result)
            exit 0
        } catch {
            # The port is available; launch the site below.
        }
    }
} finally {
    $client.Dispose()
}

Start-Process -FilePath $pythonExe `
    -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000' `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $projectRoot 'server.autostart.stdout.log') `
    -RedirectStandardError (Join-Path $projectRoot 'server.autostart.stderr.log')
