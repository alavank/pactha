$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()

$sensitiveName = '(?i)(secret|password|passwd|pwd|token|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret|database_url|postgres_url|smtp_pass|service_role|anon_key|auth_secret|signing_key|encryption_key|webhook_secret|coolify)'
$knownToken = 'AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'

function Get-Fingerprint([string] $Value) {
    if ($null -eq $Value) { $Value = '' }
    $Value = $Value.Trim()
    if (($Value.StartsWith([char]34) -and $Value.EndsWith([char]34)) -or
        ($Value.StartsWith([char]39) -and $Value.EndsWith([char]39))) {
        $Value = $Value.Substring(1, $Value.Length - 2)
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $hash = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)))).Replace('-', '').ToLower().Substring(0, 12)
    } finally {
        $sha.Dispose()
    }
    if ($Value.Length -eq 0) { return "vazio(len=0,sha256=$hash)" }
    $n = [Math]::Min(3, [Math]::Max(1, [int]($Value.Length / 3)))
    return $Value.Substring(0, $n) + '…' + $Value.Substring($Value.Length - $n) + "(len=$($Value.Length),sha256=$hash)"
}

$broadPattern = '(?i)(secret(_key)?|jwt(_secret)?|password|passwd|pwd|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret|auth[_-]?token|bearer|database_url|postgres(_password)?|smtp(_password)?|webhook(_secret)?|coolify_token|service_role|anon_key|openai|anthropic|gemini|whatsapp|evolution_api|telegram.*token|cookie_domain|session_domain|next_public_)|' + $knownToken + '|-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|[A-Za-z][A-Za-z0-9+.-]*://[^\s/:]+:[^\s/@]+@'
$files = @(& rg -l -uu -I --hidden -g '!.git/**' -g '!**/node_modules/**' -g '!**/.next/**' -g '!**/dist/**' -g '!**/__pycache__/**' -g '!**/.pytest_cache/**' -e $broadPattern .)
$seen = @{}

foreach ($file in $files) {
    $lines = [IO.File]::ReadAllLines((Resolve-Path -LiteralPath $file))
    for ($i = 0; $i -lt $lines.Length; $i++) {
        $line = $lines[$i]
        $rel = $file.TrimStart('.', '\', '/')
        $loc = $rel + ':' + ($i + 1)

        $regex = [regex]'(?i)(?:getenv|environ\.get)\(\s*["''](?<key>[^"'']+)["'']\s*,\s*(?<q>["''])(?<val>.*?)\k<q>'
        foreach ($match in $regex.Matches($line)) {
            if ($match.Groups['key'].Value -match $sensitiveName) {
                $result = $loc + ' GETENV_DEFAULT ' + $match.Groups['key'].Value + '=' + (Get-Fingerprint $match.Groups['val'].Value)
                if (!$seen[$result]) { $result; $seen[$result] = 1 }
            }
        }

        $regex = [regex]'\$\{(?<key>[A-Za-z_][A-Za-z0-9_]*)\s*:-\s*(?<val>[^}]+)\}'
        foreach ($match in $regex.Matches($line)) {
            if ($match.Groups['key'].Value -match $sensitiveName) {
                $result = $loc + ' SHELL_DEFAULT ' + $match.Groups['key'].Value + '=' + (Get-Fingerprint $match.Groups['val'].Value)
                if (!$seen[$result]) { $result; $seen[$result] = 1 }
            }
        }

        $regex = [regex]'(?i)^\s*(?:export\s+)?(?<key>[A-Za-z_][A-Za-z0-9_.-]*?(?:secret|password|passwd|pwd|token|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret|database_url|postgres_url|smtp_pass|service_role|anon_key|auth_secret|signing_key|encryption_key|webhook_secret|coolify)[A-Za-z0-9_.-]*)\s*=\s*(?<val>.*?)(?:\s+#.*)?$'
        $match = $regex.Match($line)
        if ($match.Success) {
            $value = $match.Groups['val'].Value.Trim()
            if ($value -match '^(os\.|process\.|settings\.|[A-Za-z_][A-Za-z0-9_.]*(\(|$))') { $description = 'expression' }
            else { $description = Get-Fingerprint $value }
            $result = $loc + ' ASSIGN ' + $match.Groups['key'].Value + '=' + $description
            if (!$seen[$result]) { $result; $seen[$result] = 1 }
        }

        $regex = [regex]'(?i)["''](?<key>[^"'']*?(?:secret|password|passwd|pwd|token|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret|database_url|postgres_url|smtp_pass|service_role|anon_key|auth_secret|signing_key|encryption_key|webhook_secret|coolify)[^"'']*)["'']\s*:\s*["''](?<val>[^"'']*)["'']'
        foreach ($match in $regex.Matches($line)) {
            $result = $loc + ' MAP_LITERAL ' + $match.Groups['key'].Value + '=' + (Get-Fingerprint $match.Groups['val'].Value)
            if (!$seen[$result]) { $result; $seen[$result] = 1 }
        }

        $regex = [regex]$knownToken
        foreach ($match in $regex.Matches($line)) {
            $result = $loc + ' TOKEN_PATTERN value=' + (Get-Fingerprint $match.Value)
            if (!$seen[$result]) { $result; $seen[$result] = 1 }
        }

        $regex = [regex]'(?i)(?<scheme>[A-Za-z][A-Za-z0-9+.-]*://)(?<user>[^\s/:]+):(?<pass>[^\s/@]+)@'
        foreach ($match in $regex.Matches($line)) {
            $result = $loc + ' URI_CREDENTIAL user=' + (Get-Fingerprint $match.Groups['user'].Value) + ' password=' + (Get-Fingerprint $match.Groups['pass'].Value)
            if (!$seen[$result]) { $result; $seen[$result] = 1 }
        }

        if ($line -match '-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----') {
            $result = $loc + ' PRIVATE_KEY_BLOCK'
            if (!$seen[$result]) { $result; $seen[$result] = 1 }
        }
    }
}
'TOTAL_STRUCTURED_FINDINGS=' + $seen.Count
