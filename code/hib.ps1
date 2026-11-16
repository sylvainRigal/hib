# PowerShell integration for hib. Dot-source this from your $PROFILE:
#     . C:\path\to\hib\hib.ps1
# Then `hib <args>` works everywhere, AND `hib cd <citekey>` actually changes the
# current directory of YOUR shell (the cd/cdr/cdf commands print the target dir on
# stdout; this function captures it and runs Set-Location -- something a separate
# process cannot do to its parent).
#
# Windows refuses to run ANY .ps1 -- this file, and the $PROFILE that loads it --
# under the default Restricted execution policy. Once per machine, no admin needed:
#     Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# (Check with `Get-ExecutionPolicy -List`; a MachinePolicy/UserPolicy line means a
# group policy decides and CurrentUser cannot override it -- use hib.bat in cmd.exe
# there, it has the same cd behaviour and no policy applies to a .bat.)
#
# It drives hib.exe when one sits next to this file (or in .\bin), else the Python
# sources. So the same $PROFILE line works for a source checkout and for a machine
# where only hib.exe + hib.ps1 were copied.

function hib {
    $exe = $null
    foreach ($candidate in @((Join-Path $PSScriptRoot 'hib.exe'),
                             (Join-Path $PSScriptRoot 'bin\hib.exe'))) {
        if (Test-Path -LiteralPath $candidate) { $exe = $candidate; break }
    }
    if ($exe) {
        $cmd = $exe; $pre = @()
    } else {
        $script = Join-Path $PSScriptRoot 'hib.py'
        # -E -s run Python ISOLATED: ignore PYTHONPATH/PYTHONHOME and the user site dir,
        # so a foreign Python stdlib (e.g. set by another app's PYTHONHOME) is never
        # mixed in -- the cause of "AssertionError: SRE module mismatch". HIB_CONFIG /
        # LOCALAPPDATA are still read normally (via os.environ).
        if (Get-Command py -ErrorAction SilentlyContinue) { $cmd = 'py'; $pre = @('-3', '-E', '-s', $script) }
        else { $cmd = 'python'; $pre = @('-E', '-s', $script) }
    }

    if ($args.Count -ge 1 -and @('cd', 'cdr', 'cdf') -contains $args[0]) {
        # cd/cdr/cdf print only the directory on stdout (prompts/errors go to stderr).
        $dir = & $cmd @pre @args
        if ($LASTEXITCODE -eq 0 -and $dir) { Set-Location -LiteralPath $dir }
    } else {
        & $cmd @pre @args
    }
}
