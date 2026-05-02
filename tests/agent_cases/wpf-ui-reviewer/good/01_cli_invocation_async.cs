// GOOD: async invocation, CancellationToken, timeout, no UI thread blocking,
// strongly-typed envelope, all exit codes mapped, no SQLite reference.
using System;
using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;

namespace FinanzasMMEX.App.Services;

public sealed record CliEnvelope(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("data")] JsonElement Data,
    [property: JsonPropertyName("errors")] CliError[] Errors,
    [property: JsonPropertyName("warnings")] string[] Warnings,
    [property: JsonPropertyName("run_id")] string RunId
);

public sealed record CliError(string Code, string Message, JsonElement? Details);

public sealed class PythonCli
{
    public async Task<(int ExitCode, CliEnvelope? Envelope, string Stderr)> InvokeAsync(
        string[] args, TimeSpan timeout, CancellationToken ct)
    {
        var psi = new ProcessStartInfo("finanzasmmex")
        {
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
        };
        foreach (var a in args) psi.ArgumentList.Add(a);

        using var proc = Process.Start(psi)!;
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(timeout);

        var stdoutTask = proc.StandardOutput.ReadToEndAsync(cts.Token);
        var stderrTask = proc.StandardError.ReadToEndAsync(cts.Token);
        await proc.WaitForExitAsync(cts.Token);
        var stdout = await stdoutTask;
        var stderr = await stderrTask;

        CliEnvelope? envelope = null;
        try { envelope = JsonSerializer.Deserialize<CliEnvelope>(stdout); }
        catch (JsonException) { /* malformed handled by caller */ }

        return (proc.ExitCode, envelope, stderr);
    }
}
