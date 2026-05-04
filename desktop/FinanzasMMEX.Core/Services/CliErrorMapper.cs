using FinanzasMMEX.Core.Cli;

namespace FinanzasMMEX.Core.Services;

/// <summary>
/// Translates the CLI envelope + exit code into a user-facing message.
/// Centralised so views never sniff exit codes manually.
/// </summary>
public static class CliErrorMapper
{
    public static string Describe(CliResult result)
    {
        if (result.IsSuccess)
        {
            return string.Empty;
        }

        var firstError = result.Envelope?.Errors.FirstOrDefault();
        var detail = firstError?.Message;

        return result.ExitCode switch
        {
            CliExitCode.Success when result.Envelope?.Ok == false =>
                FormatWithDetail("CLI reportó ok=false sin errores en el envelope.", detail),
            CliExitCode.ValidationError =>
                FormatWithDetail("Datos inválidos.", detail),
            CliExitCode.CredentialsRequired =>
                FormatWithDetail(
                    "Faltan credenciales; ejecute login antes de reintentar.",
                    detail),
            CliExitCode.MmexLocked =>
                FormatWithDetail(
                    "MMEX está abierto y bloqueando la base; cierre la app y reintente.",
                    detail),
            CliExitCode.TemporaryFailure => FormatWithDetail(
                BuildTemporaryFailureHeadline(result.RawExitCode),
                detail),
            _ => FormatWithDetail(
                $"Código de salida desconocido ({result.RawExitCode}).",
                detail),
        };
    }

    private static string FormatWithDetail(string headline, string? detail) =>
        string.IsNullOrWhiteSpace(detail) ? headline : $"{headline} {detail}";

    private static string BuildTemporaryFailureHeadline(int rawExitCode) =>
        rawExitCode == (int)CliExitCode.TemporaryFailure
            ? "Falla temporal; reintente en unos segundos."
            : $"Falla temporal (código {rawExitCode}); reintente en unos segundos.";
}
