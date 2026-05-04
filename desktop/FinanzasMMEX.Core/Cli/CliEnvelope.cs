using System.Text.Json;
using System.Text.Json.Serialization;

namespace FinanzasMMEX.Core.Cli;

public sealed record CliError(
    [property: JsonPropertyName("code")] string Code,
    [property: JsonPropertyName("message")] string Message,
    [property: JsonPropertyName("details")] JsonElement? Details
);

public sealed record CliEnvelope(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("data")] JsonElement? Data,
    [property: JsonPropertyName("errors")] IReadOnlyList<CliError> Errors,
    [property: JsonPropertyName("warnings")] IReadOnlyList<string> Warnings,
    [property: JsonPropertyName("run_id")] string RunId
)
{
    /// <summary>
    /// Returns the first error code or <c>null</c> when none is present.
    /// </summary>
    public string? FirstErrorCode => Errors.Count > 0 ? Errors[0].Code : null;
}

/// <summary>
/// Result of running the CLI: parsed envelope + raw process metadata. The CLI
/// is the only writer to <c>staging.db</c>, so the UI consumes envelopes only.
/// </summary>
public sealed record CliResult(
    CliExitCode ExitCode,
    int RawExitCode,
    CliEnvelope? Envelope,
    string StdOut,
    string StdErr
)
{
    public bool IsSuccess => ExitCode == CliExitCode.Success && Envelope?.Ok == true;
}

public static class CliEnvelopeParser
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        ReadCommentHandling = JsonCommentHandling.Skip,
    };

    public static CliEnvelope? TryParse(string stdout)
    {
        if (string.IsNullOrWhiteSpace(stdout))
        {
            return null;
        }

        try
        {
            return JsonSerializer.Deserialize<CliEnvelope>(stdout, Options);
        }
        catch (JsonException)
        {
            return null;
        }
    }
}
