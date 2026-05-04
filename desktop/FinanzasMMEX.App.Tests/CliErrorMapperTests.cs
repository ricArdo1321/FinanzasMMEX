using System.Text.Json;
using FinanzasMMEX.Core.Cli;
using FinanzasMMEX.Core.Services;
using Xunit;

namespace FinanzasMMEX.App.Tests;

public class CliErrorMapperTests
{
    private static CliResult Failure(CliExitCode code, string? errorMessage = null)
    {
        var errors = errorMessage is null
            ? Array.Empty<CliError>()
            : new[] { new CliError("CODE", errorMessage, null) };
        var envelope = new CliEnvelope(
            Ok: false,
            Data: null,
            Errors: errors,
            Warnings: Array.Empty<string>(),
            RunId: "run"
        );
        return new CliResult(code, (int)code, envelope, "{}", "");
    }

    [Fact]
    public void Validation_error_message_includes_detail()
    {
        var msg = CliErrorMapper.Describe(Failure(CliExitCode.ValidationError, "tx_uid missing"));
        Assert.Contains("Datos inválidos", msg);
        Assert.Contains("tx_uid missing", msg);
    }

    [Fact]
    public void Credentials_required_message_mentions_login()
    {
        var msg = CliErrorMapper.Describe(Failure(CliExitCode.CredentialsRequired));
        Assert.Contains("login", msg);
    }

    [Fact]
    public void Mmex_locked_message_advises_to_close_mmex()
    {
        var msg = CliErrorMapper.Describe(Failure(CliExitCode.MmexLocked));
        Assert.Contains("MMEX", msg);
    }

    [Fact]
    public void Temporary_failure_suggests_retry()
    {
        var msg = CliErrorMapper.Describe(Failure(CliExitCode.TemporaryFailure));
        Assert.Contains("reintente", msg, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Success_returns_empty_message()
    {
        var envelope = new CliEnvelope(true, JsonDocument.Parse("{}").RootElement,
            Array.Empty<CliError>(), Array.Empty<string>(), "id");
        var result = new CliResult(CliExitCode.Success, 0, envelope, "{}", "");
        Assert.Empty(CliErrorMapper.Describe(result));
    }

    [Fact]
    public void Unknown_raw_exit_code_falls_back()
    {
        var envelope = new CliEnvelope(false, null, Array.Empty<CliError>(),
            Array.Empty<string>(), "id");
        var result = new CliResult(CliExitCode.TemporaryFailure, 137, envelope, "", "killed");
        // The mapper still routes via CliExitCode.TemporaryFailure,
        // because CliExitCodes.FromInt collapses unknown codes to TemporaryFailure.
        var msg = CliErrorMapper.Describe(result);
        Assert.Contains("Falla temporal", msg);
    }
}
