using System.Diagnostics;
using System.Text;

namespace FinanzasMMEX.Core.Cli;

public sealed class CliRunnerOptions
{
    /// <summary>
    /// Executable used to launch the CLI. Defaults to the Windows Python launcher
    /// <c>py</c>, which is available on every supported dev machine.
    /// </summary>
    public string Executable { get; init; } = "py";

    /// <summary>
    /// Arguments injected before the user-supplied subcommand. The default
    /// invokes the FinanzasMMEX module via the Python launcher.
    /// </summary>
    public IReadOnlyList<string> BaseArguments { get; init; } =
        new[] { "-3", "-m", "finanzasmmex.cli" };

    public string? WorkingDirectory { get; init; }

    public IReadOnlyDictionary<string, string?>? Environment { get; init; }

    /// <summary>
    /// Hard cap for a CLI invocation. Read-only commands (review/quickadd) finish
    /// in well under a second; longer-running ingestion (<c>run</c>) should
    /// override this via a per-call options override. Default: 30 seconds.
    /// </summary>
    public TimeSpan Timeout { get; init; } = TimeSpan.FromSeconds(30);
}

public interface ICliRunner
{
    Task<CliResult> RunAsync(IEnumerable<string> arguments, CancellationToken ct = default);
}

public sealed class CliRunner : ICliRunner
{
    private readonly CliRunnerOptions _options;

    public CliRunner(CliRunnerOptions? options = null)
    {
        _options = options ?? new CliRunnerOptions();
    }

    public async Task<CliResult> RunAsync(
        IEnumerable<string> arguments,
        CancellationToken ct = default)
    {
        var psi = new ProcessStartInfo
        {
            FileName = _options.Executable,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };

        if (!string.IsNullOrWhiteSpace(_options.WorkingDirectory))
        {
            psi.WorkingDirectory = _options.WorkingDirectory!;
        }

        foreach (var baseArg in _options.BaseArguments)
        {
            psi.ArgumentList.Add(baseArg);
        }

        foreach (var arg in arguments)
        {
            psi.ArgumentList.Add(arg);
        }

        if (_options.Environment is not null)
        {
            foreach (var kv in _options.Environment)
            {
                psi.Environment[kv.Key] = kv.Value;
            }
        }

        using var process = new Process { StartInfo = psi, EnableRaisingEvents = true };
        var stdoutBuffer = new StringBuilder();
        var stderrBuffer = new StringBuilder();

        process.OutputDataReceived += (_, e) =>
        {
            if (e.Data is not null) stdoutBuffer.AppendLine(e.Data);
        };
        process.ErrorDataReceived += (_, e) =>
        {
            if (e.Data is not null) stderrBuffer.AppendLine(e.Data);
        };

        if (!process.Start())
        {
            throw new InvalidOperationException("Could not start CLI process");
        }

        process.BeginOutputReadLine();
        process.BeginErrorReadLine();

        using var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        linkedCts.CancelAfter(_options.Timeout);

        bool timedOut = false;
        try
        {
            await process.WaitForExitAsync(linkedCts.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            timedOut = !ct.IsCancellationRequested;
            try
            {
                if (!process.HasExited)
                {
                    process.Kill(entireProcessTree: true);
                    // Give the async readers a brief window to drain stderr,
                    // which usually carries the diagnostic for hung processes.
                    using var drainCts = new CancellationTokenSource(
                        TimeSpan.FromMilliseconds(500));
                    await process.WaitForExitAsync(drainCts.Token).ConfigureAwait(false);
                }
            }
            catch (OperationCanceledException)
            {
                // Drain timeout elapsed; keep returning the timeout diagnostic.
            }
            catch
            {
                // Process already exited or kill raced with exit; swallow.
            }

            if (!timedOut)
            {
                throw;
            }
        }

        var stdout = stdoutBuffer.ToString();
        var stderr = stderrBuffer.ToString();
        if (timedOut)
        {
            return new CliResult(
                CliExitCode.TemporaryFailure,
                process.HasExited ? process.ExitCode : -1,
                Envelope: null,
                StdOut: stdout,
                StdErr: stderr.Length > 0
                    ? stderr
                    : $"CLI excedió el timeout de {_options.Timeout.TotalSeconds:0}s"
            );
        }
        var envelope = CliEnvelopeParser.TryParse(stdout);
        var exitCode = CliExitCodes.FromInt(process.ExitCode);

        return new CliResult(exitCode, process.ExitCode, envelope, stdout, stderr);
    }
}
